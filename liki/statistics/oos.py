"""Predeclared chronological validation of a frozen G5 program and G6 cost policy."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator, model_validator

from liki.backtest_gate import BacktestPlan, QuoteReplayData, StrategyProgram, replay
from liki.core import Contract, canonical, content_hash
from liki.data.models import ensure_utc
from liki.finance.economics import evaluate_economics
from liki.finance.economics_contracts import EconomicsPolicy, ExecutionTape

OOS_VERSION = "chronological-fixed-program-v1"


class OOSDeclaration(Contract):
    protocol_version: Literal["chronological-fixed-program-v1"]
    snapshot_id: str = Field(min_length=1)
    candidate_artifact_id: str = Field(min_length=1)
    candidate_hash: str = Field(min_length=1)
    g5_configuration_hash: str = Field(min_length=1)
    g6_policy_hash: str = Field(min_length=1)
    g6_execution_tape_hash: str = Field(min_length=1)
    quote_dataset_snapshot_id: str = Field(min_length=1)
    execution_dataset_snapshot_id: str = Field(min_length=1)
    trial_event_id: str = Field(min_length=1)
    trial_family_id: str = Field(min_length=1)
    test_start: datetime
    observation_interval_ms: int = Field(gt=0, le=86400000, strict=True)
    observations: int = Field(ge=3, le=10000, strict=True)
    event_horizon_seconds: int = Field(gt=0, strict=True)
    embargo_seconds: int = Field(ge=0, strict=True)
    method_rationale: str = Field(min_length=1, pattern=r"\S")
    fitting: Literal["NONE_FROZEN_G5_PROGRAM"]
    initial_state: Literal["CASH_ONLY_COLD_START"]
    scoring: Literal["ALL_G6_SCENARIOS_AT_INTENDED_SIZE"]
    code_hash: str = Field(min_length=1)

    _utc = field_validator("test_start")(ensure_utc)

    @property
    def interval(self) -> timedelta:
        return timedelta(milliseconds=self.observation_interval_ms)

    @property
    def test_end(self) -> datetime:
        return self.test_start + (self.observations - 1) * self.interval

    @model_validator(mode="after")
    def independent_window(self) -> OOSDeclaration:
        if self.quote_dataset_snapshot_id == self.execution_dataset_snapshot_id:
            raise ValueError("quote and execution sources require separate snapshot identities")
        if self.embargo_seconds < self.event_horizon_seconds:
            raise ValueError("embargo cannot be shorter than the declared event horizon")
        if (self.test_end - self.test_start).total_seconds() < self.event_horizon_seconds:
            raise ValueError("validation window must cover at least one declared event horizon")
        return self


class OOSPlan(Contract):
    declaration_artifact_id: str = Field(min_length=1)
    quote_dataset_artifact_id: str = Field(min_length=1)
    execution_dataset_artifact_id: str = Field(min_length=1)


def evaluate_oos(declaration: OOSDeclaration, g5: dict, g6: dict,
                 quotes: QuoteReplayData, tape: ExecutionTape, development_tape: ExecutionTape) -> dict:
    """No fitting, window selection, cost calibration or threshold retuning occurs here."""
    for body, expected, name in ((g5["configuration"], declaration.g5_configuration_hash, "g5"),
            (g6["policy"], declaration.g6_policy_hash, "g6_policy"),
            (development_tape.model_dump(mode="json"), declaration.g6_execution_tape_hash, "g6_execution_tape")):
        if content_hash(body) != expected:
            raise ValueError("G7_FROZEN_CONFIGURATION_MISMATCH:" + name)
    expected_times = tuple(declaration.test_start + i * declaration.interval for i in range(declaration.observations))
    if tuple(row.timestamp for row in quotes.quotes) != expected_times:
        raise ValueError("G7_PREDECLARED_OBSERVATION_GRID_MISMATCH")
    development_end = datetime.fromisoformat(g5["candidate"]["observations"][-1]["timestamp"])
    event_end = development_end + timedelta(seconds=declaration.event_horizon_seconds)
    if expected_times[0] <= event_end + timedelta(seconds=declaration.embargo_seconds):
        raise ValueError("G7_DEVELOPMENT_EVENT_OR_EMBARGO_OVERLAP")
    strategy = StrategyProgram.model_validate(g5["strategy"])
    if declaration.observations <= strategy.lookback + 2:
        raise ValueError("G7_INSUFFICIENT_POST_WARMUP_OBSERVATIONS")
    if (tape.evidence_kind == "SYNTHETIC" or tape.latency_samples != development_tape.latency_samples
            or tape.latency_source != development_tape.latency_source
            or tape.base_fee_tier != development_tape.base_fee_tier):
        raise ValueError("G7_EXECUTION_ASSUMPTIONS_RETUNED_OR_SYNTHETIC")
    unit_fields = ("venue", "instrument_id", "base_currency", "quote_currency", "settlement_currency", "contract_kind", "multiplier")
    original_spec = development_tape.rules[0].specification
    for spec in (quotes.instrument, *(row.specification for row in tape.rules)):
        if any(getattr(spec, field) != getattr(original_spec, field) for field in unit_fields):
            raise ValueError("G7_ECONOMIC_UNIT_MISMATCH")
    if tuple(row.event_time for row in tape.books) != (expected_times[0] - declaration.interval, *expected_times):
        raise ValueError("G7_EXECUTION_GRID_MISMATCH")
    if any((quote.bid, quote.ask) != (book.bids[0].price, book.asks[0].price)
           for quote, book in zip(quotes.quotes, tape.books[1:], strict=True)):
        raise ValueError("G7_QUOTE_DEPTH_OBSERVATION_CONFLICT")
    plan_body = {**g5["configuration"], "dataset_artifact_id": tape.g5_dataset_artifact_id,
        "scenarios": [{"name": "predeclared-oos", "start": declaration.test_start,
                       "end": declaration.test_end + declaration.interval}]}
    intent_package = json.loads(canonical(replay(BacktestPlan.model_validate(plan_body), quotes, strategy)))
    costs = evaluate_economics(intent_package, tape, EconomicsPolicy.model_validate(g6["policy"]))
    intended = next(row for row in costs["capacity_curve"] if row["size_multiplier"] == 1)
    return {"protocol_version": OOS_VERSION, "declaration": declaration.model_dump(mode="json"),
        "split": {"method": "CHRONOLOGICAL", "development_last_observation": development_end,
            "development_event_end": event_end, "embargo_seconds": declaration.embargo_seconds,
            "test_start": declaration.test_start, "test_end": declaration.test_end,
            "observations": declaration.observations, "fitting": declaration.fitting,
            "purge": "ALL_DEVELOPMENT_EVENTS_END_BEFORE_EMBARGO; NO_OOS_FITTING"},
        "intent_generation": intent_package, "execution_economics": costs,
        "score": intended, "checks": dict.fromkeys(("predeclared_split", "no_tuning_leakage", "purge_embargo", "trial_history_complete"), True),
        "hard_invalidity": costs["hard_invalidity"],
        "failure_reasons": [reason.replace("G6_", "G7_OOS_") for reason in costs["failure_reasons"]],
        "limitations": ["Frozen program; no fitted model, rolling retraining or nested selection is claimed",
            "Cold-start, cash-only validation; no development PnL or positions are carried into OOS",
            "Conditional G6 scenario ranges, not statistical significance or independent market confirmation",
            "Validation results become research exposure; they are not a reusable sealed holdout"]}
