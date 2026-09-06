"""Immutable data-layer schemas. All timestamps are timezone-aware UTC."""

from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def ensure_utc(value: datetime) -> datetime:
    """Reject naive/non-UTC timestamps instead of silently changing their meaning."""
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError("timestamp must be timezone-aware")
    if offset.total_seconds() != 0:
        raise ValueError("timestamp must be expressed in UTC")
    return value.astimezone(UTC)


def ensure_optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else ensure_utc(value)


class QualityStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    QUARANTINED = "quarantined"


class FidelityTier(StrEnum):
    F0_BAR = "F0_BAR"
    F1_TRADE_BBO = "F1_TRADE_BBO"
    F2_AGG_L2 = "F2_AGG_L2"
    F3_SEQ_L2 = "F3_SEQ_L2"
    F4_ORDER_LEVEL = "F4_ORDER_LEVEL"
    F5_ACCOUNT_OBSERVED = "F5_ACCOUNT_OBSERVED"


class PriceKind(StrEnum):
    INDEX = "index"
    MARK = "mark"
    LAST = "last"
    TRADE = "trade"
    BBO = "bbo"


class RawPayload(BaseModel):
    """A content-addressed, immutable source response and its retrieval provenance."""

    model_config = ConfigDict(frozen=True)

    content_hash: str
    provider: str
    uri: str
    retrieved_at: datetime
    content_type: str = "application/json"
    provider_revision_id: str | None = None
    transport_metadata: dict[str, str] = Field(default_factory=dict)
    payload_bytes: bytes = Field(default=b"", repr=False, exclude=True)

    _utc = field_validator("retrieved_at")(ensure_utc)

    @classmethod
    def from_bytes(
        cls, *, provider: str, uri: str, content: bytes, retrieved_at: datetime, **kwargs: Any
    ) -> RawPayload:
        return cls(
            content_hash=f"sha256:{sha256(content).hexdigest()}",
            provider=provider,
            uri=uri,
            retrieved_at=retrieved_at,
            payload_bytes=content,
            **kwargs,
        )


class DatasetManifest(BaseModel):
    """Snapshot contract used by all promoted data and feature artifacts."""

    model_config = ConfigDict(frozen=True)

    dataset_snapshot_id: str
    provider: str
    venue: str
    instrument: str
    instrument_type: str
    timezone: str = "UTC"
    start_time: datetime
    end_time: datetime
    as_of_time: datetime
    fetched_at: datetime
    candle_semantics: str
    timestamp_semantics: str
    provider_revision_id: str | None = None
    missing_intervals: tuple[tuple[datetime, datetime], ...] = ()
    repair_events: tuple[dict[str, Any], ...] = ()
    duplicates_removed: int = Field(ge=0, default=0)
    bad_ticks_removed: int = Field(ge=0, default=0)
    corporate_action_policy: str | None = None
    delisting_policy: str
    survivorship_policy: str
    freshness_sec: int = Field(ge=0)
    freshness_sla_sec: int = Field(ge=0)
    schema_hash: str
    content_hash: str
    quality_status: QualityStatus
    raw_payload_hashes: tuple[str, ...] = ()
    license_restrictions: str | None = None
    retention_until: datetime | None = None
    fidelity_tier: FidelityTier = FidelityTier.F0_BAR
    coverage_limitations: tuple[str, ...] = ()

    _timestamps = field_validator("start_time", "end_time", "as_of_time", "fetched_at")(ensure_utc)
    _optional_timestamp = field_validator("retention_until")(ensure_optional_utc)

    @field_validator("timezone")
    @classmethod
    def utc_only(cls, value: str) -> str:
        if value != "UTC":
            raise ValueError("LIKI canonical data timestamps must use UTC")
        return value

    @model_validator(mode="after")
    def chronology_and_freshness(self) -> DatasetManifest:
        if self.end_time < self.start_time:
            raise ValueError("end_time precedes start_time")
        if self.as_of_time < self.end_time:
            raise ValueError("as_of_time precedes dataset end_time")
        if self.freshness_sec > self.freshness_sla_sec and self.quality_status in {
            QualityStatus.PASS,
            QualityStatus.WARN,
        }:
            raise ValueError("stale data must be failed or quarantined")
        if not self.raw_payload_hashes:
            raise ValueError("dataset must retain immutable raw provenance pointers")
        for start, end in self.missing_intervals:
            start, end = ensure_utc(start), ensure_utc(end)
            if end <= start:
                raise ValueError("missing interval must have positive UTC duration")
        return self


class CanonicalMarketRecord(BaseModel):
    """Normalized record retaining source timing and raw content pointer."""

    model_config = ConfigDict(frozen=True)

    instrument_id: str
    event_time: datetime
    available_at: datetime
    price: Decimal = Field(gt=0)
    quantity: Decimal | None = Field(default=None, ge=0)
    price_kind: PriceKind
    raw_payload_hash: str

    _utc = field_validator("event_time", "available_at")(ensure_utc)

    @model_validator(mode="after")
    def not_available_before_event(self) -> CanonicalMarketRecord:
        if self.available_at < self.event_time:
            raise ValueError("available_at cannot precede event_time")
        return self
