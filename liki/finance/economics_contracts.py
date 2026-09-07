"""Immutable execution-economics inputs; unknown inputs have no numeric defaults."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, field_validator, model_validator

from liki.core import Contract
from liki.data.models import ensure_optional_utc, ensure_utc
from .types import FeeSchedule, FidelityTier, InstrumentSpec, decimal


def amount(value) -> Decimal:
    if isinstance(value, (float, bool)):
        raise ValueError("money requires decimal text or integer native units")
    return decimal(value)


Amount = Annotated[Decimal, BeforeValidator(amount)]


class DepthLevel(Contract):
    price: Amount = Field(gt=0)
    quantity: Amount = Field(ge=0)


class BookObservation(Contract):
    event_time: datetime
    available_at: datetime
    bids: tuple[DepthLevel, ...] = Field(min_length=1)
    asks: tuple[DepthLevel, ...] = Field(min_length=1)
    traded_quantity: Amount = Field(ge=0)
    volume_window_start: datetime
    fidelity: FidelityTier
    sequence_status: Literal["VALIDATED", "SNAPSHOT_ONLY", "GAP"]
    sequence_start: int | None = Field(default=None, ge=0, strict=True)
    sequence_end: int | None = Field(default=None, ge=0, strict=True)
    outage: bool

    _utc = field_validator("event_time", "available_at", "volume_window_start")(ensure_utc)

    @model_validator(mode="after")
    def ordered(self) -> BookObservation:
        bids, asks = [x.price for x in self.bids], [x.price for x in self.asks]
        if bids != sorted(set(bids), reverse=True) or asks != sorted(set(asks)) or bids[0] > asks[0]:
            raise ValueError("depth levels must be unique, ordered and uncrossed")
        if not self.volume_window_start < self.event_time <= self.available_at:
            raise ValueError("volume and order book must be causally available")
        if (self.sequence_start is None) != (self.sequence_end is None):
            raise ValueError("both sequence endpoints are required")
        if self.sequence_start is not None and self.sequence_end is not None and self.sequence_end < self.sequence_start:
            raise ValueError("invalid sequence range")
        return self


class VenueRule(Contract):
    specification: InstrumentSpec
    available_at: datetime
    fee_increment: Amount = Field(gt=0)
    max_order_notional: Amount = Field(gt=0)
    max_position_quantity: Amount = Field(gt=0)
    message_limit: int = Field(gt=0)
    message_window_ms: int = Field(gt=0)
    max_price_deviation_bps: Amount = Field(ge=0)
    supported_order_types: tuple[Literal["MARKET", "LIMIT"], ...] = Field(min_length=1)

    _utc = field_validator("available_at")(ensure_utc)


class FeeObservation(Contract):
    schedule: FeeSchedule
    available_at: datetime

    _utc = field_validator("available_at")(ensure_utc)


class AccountTier(Contract):
    tier: str = Field(min_length=1)
    effective_from: datetime
    effective_to: datetime | None
    available_at: datetime
    basis: Literal["OBSERVED_ACCOUNT", "CONSERVATIVE_BASE"]
    source: str = Field(min_length=1, pattern=r"\S")

    _utc = field_validator("effective_from", "available_at")(ensure_utc)
    _optional_utc = field_validator("effective_to")(ensure_optional_utc)

    @model_validator(mode="after")
    def interval(self) -> AccountTier:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("invalid account-tier interval")
        return self


class LatencySample(Contract):
    sample_id: str = Field(min_length=1)
    signal_ms: int = Field(ge=0, strict=True)
    decision_ms: int = Field(ge=0, strict=True)
    network_ms: int = Field(ge=0, strict=True)
    acknowledgement_ms: int = Field(ge=0, strict=True)
    cancel_ms: int = Field(ge=0, strict=True)
    market_data_ms: int = Field(ge=0, strict=True)


class ExecutionTape(Contract):
    schema_version: Literal["execution-economics-tape-v1"]
    venue: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    g5_dataset_artifact_id: str = Field(min_length=1)
    base_fee_tier: str = Field(min_length=1)
    rules: tuple[VenueRule, ...] = Field(min_length=1)
    fees: tuple[FeeObservation, ...] = Field(min_length=1)
    account_tiers: tuple[AccountTier, ...] = Field(min_length=1)
    books: tuple[BookObservation, ...] = Field(min_length=2, max_length=20000)
    latency_samples: tuple[LatencySample, ...] = Field(min_length=3, max_length=1000)
    evidence_kind: Literal["HISTORICAL_PUBLIC", "OBSERVED_PAPER", "SYNTHETIC"]
    latency_source: str = Field(min_length=1, pattern=r"\S")
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def identities(self) -> ExecutionTape:
        times = [b.event_time for b in self.books]
        if times != sorted(set(times)):
            raise ValueError("execution tape must be strictly chronological")
        if len({row.sample_id for row in self.latency_samples}) != len(self.latency_samples):
            raise ValueError("latency sample IDs must be unique")
        if any((r.specification.venue, r.specification.instrument_id) != (self.venue, self.instrument_id)
               for r in self.rules):
            raise ValueError("venue-rule identity mismatch")
        if any(row.basis == "CONSERVATIVE_BASE" and row.tier != self.base_fee_tier for row in self.account_tiers):
            raise ValueError("unknown account state cannot claim a favorable hypothetical tier")
        return self


class ImpactBounds(Contract):
    version: str = Field(min_length=1)
    lower_bps: Amount = Field(ge=0)
    central_bps: Amount = Field(ge=0)
    upper_bps: Amount = Field(ge=0)
    calibration_raw_hashes: tuple[str, ...] = Field(min_length=1)
    validation_raw_hashes: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def bounds(self) -> ImpactBounds:
        if not self.lower_bps <= self.central_bps <= self.upper_bps:
            raise ValueError("impact uncertainty bounds are reversed")
        if set(self.calibration_raw_hashes) & set(self.validation_raw_hashes):
            raise ValueError("calibration and validation episodes must be disjoint")
        return self


class ImpactMeasurement(Contract):
    episode_id: str = Field(min_length=1)
    timestamp: datetime
    available_at: datetime
    participation: Amount = Field(gt=0, le=1)
    residual_impact_bps: Amount = Field(ge=0)

    _utc = field_validator("timestamp", "available_at")(ensure_utc)

    @model_validator(mode="after")
    def causal(self) -> ImpactMeasurement:
        if self.available_at < self.timestamp:
            raise ValueError("impact measurement predates its execution")
        return self


class ImpactSampleSet(Contract):
    schema_version: Literal["execution-impact-samples-v1"]
    venue: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    observations: tuple[ImpactMeasurement, ...] = Field(min_length=3, max_length=10000)
    measurement_basis: Literal["ISOLATED_RESIDUAL_EXCLUDING_FEES_SPREAD_DEPTH_TIMING"]
    evidence: Literal["MODEL_ESTIMATE", "ACCOUNT_OBSERVED"]
    source: str = Field(min_length=1, pattern=r"\S")


class EconomicsPolicy(Contract):
    version: str = Field(min_length=1)
    size_multipliers: tuple[Amount, ...] = Field(min_length=3, max_length=20)
    participation_limit: Amount = Field(gt=0, le=1)
    displayed_depth_fraction: Amount = Field(gt=0, le=1)
    adverse_depth_fraction: Amount = Field(gt=0, le=1)
    stale_after_ms: int = Field(gt=0)
    acknowledgement_timeout_ms: int = Field(gt=0)
    max_gap_ms: int = Field(gt=0)
    minimum_fidelity: Literal["F2_AGG_L2", "F3_SEQ_L2", "F4_ORDER_LEVEL", "F5_ACCOUNT_OBSERVED"]
    minimum_fill_ratio: Amount = Field(gt=0, le=1)
    minimum_worst_net_return: Amount = Field(ge=0)
    minimum_worst_excess_return: Amount = Field(ge=0)
    impact: ImpactBounds

    @model_validator(mode="after")
    def stress(self) -> EconomicsPolicy:
        if (list(self.size_multipliers) != sorted(set(self.size_multipliers))
                or min(self.size_multipliers) <= 0 or Decimal("1") not in self.size_multipliers
                or min(self.size_multipliers) >= 1 or max(self.size_multipliers) <= 1):
            raise ValueError("capacity grid must bracket intended size with distinct positive scales")
        if self.adverse_depth_fraction >= self.displayed_depth_fraction:
            raise ValueError("adverse-fill case must reduce assumed executable depth")
        return self


class EconomicsPlan(Contract):
    candidate_artifact_id: str = Field(min_length=1)
    candidate_hash: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    execution_dataset_artifact_id: str = Field(min_length=1)
    policy_artifact_id: str = Field(min_length=1)
    code_hash: str = Field(min_length=1)
    protocol_version: Literal["depth-execution-economics-v1"]
    hidden_liquidity: Literal["NONE_ASSUMED"]
    queue_assumption: Literal["NO_PASSIVE_FILLS"]
    funding: Literal["NOT_APPLICABLE_SPOT"]
    borrow_financing: Literal["NOT_APPLICABLE_FULLY_FUNDED_LONG_ONLY"]
    liquidation: Literal["NOT_APPLICABLE_NO_MARGIN"]
