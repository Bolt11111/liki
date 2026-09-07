"""Source reconciliation and clock-drift checks for promotion-sensitive data."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from .models import QualityStatus, ensure_utc
from .validation import FindingKind, ValidationFinding


class DisagreementClass(StrEnum):
    TIMESTAMP_CONVENTION = "timestamp_convention"
    SYMBOL_MAPPING = "symbol_mapping"
    STALE_SOURCE = "stale_source"
    VENUE_DIFFERENCE = "venue_difference"
    VENDOR_REPAIR = "vendor_repair"
    MARKET_DISCREPANCY = "actual_market_discrepancy"
    UNRESOLVED = "unresolved"


class ReconciliationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    comparison_id: str
    primary_provider: str
    comparison_provider: str
    classification: DisagreementClass
    compared_at: datetime
    rationale: str
    primary_raw_hash: str
    comparison_raw_hash: str

    _utc = field_validator("compared_at")(ensure_utc)

    def finding(self) -> ValidationFinding | None:
        if self.classification != DisagreementClass.UNRESOLVED:
            return None
        return ValidationFinding(
            kind=FindingKind.PROVIDER_DISAGREEMENT,
            severity=QualityStatus.FAIL,
            reason=self.rationale,
            at=self.compared_at,
            raw_payload_hashes=(self.primary_raw_hash, self.comparison_raw_hash),
        )


class ClockMeasurement(BaseModel):
    model_config = ConfigDict(frozen=True)

    measured_at: datetime
    local_receive_before: datetime
    local_receive_after: datetime
    venue_time: datetime
    maximum_offset: timedelta

    _utc = field_validator(
        "measured_at", "local_receive_before", "local_receive_after", "venue_time"
    )(ensure_utc)

    @property
    def offset(self) -> timedelta:
        midpoint = (
            self.local_receive_before + (self.local_receive_after - self.local_receive_before) / 2
        )
        return self.venue_time - midpoint

    @property
    def round_trip(self) -> timedelta:
        return self.local_receive_after - self.local_receive_before

    def latency_sensitive_usable(self) -> bool:
        return self.round_trip >= timedelta(0) and abs(self.offset) <= self.maximum_offset
