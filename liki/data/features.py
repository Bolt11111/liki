"""Leakage-safe bars, as-of joins, and shared online/offline feature evaluation."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import CanonicalMarketRecord, ensure_utc


class Bar(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: datetime
    end_time: datetime
    label_time: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    complete: bool
    latest_source_timestamp_used: datetime

    _utc = field_validator("start_time", "end_time", "label_time", "latest_source_timestamp_used")(
        ensure_utc
    )

    @model_validator(mode="after")
    def range_and_completion(self) -> Bar:
        if not self.start_time < self.end_time or self.label_time != self.end_time:
            raise ValueError("bar labels are UTC interval end timestamps")
        if (
            not self.low <= min(self.open, self.close) <= self.high
            or not self.low <= self.close <= self.high
        ):
            raise ValueError("OHLC values violate bar range")
        if self.latest_source_timestamp_used > self.end_time:
            raise ValueError("bar uses source after its interval")
        return self


class FeatureDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature_id: str
    version: str
    source_columns: tuple[str, ...]
    lookback: timedelta
    missing_value_policy: str
    normalization_policy: str
    availability_semantics: str
    code_hash: str

    @classmethod
    def for_callable(
        cls, *, feature_id: str, version: str, function: Callable[..., object], **kwargs: object
    ) -> FeatureDefinition:
        return cls.model_validate(
            {
                "feature_id": feature_id,
                "version": version,
                "code_hash": f"sha256:{sha256(inspect.getsource(function).encode()).hexdigest()}",
                **kwargs,
            }
        )


class FeatureResult[T](BaseModel):
    model_config = ConfigDict(frozen=True)

    definition: FeatureDefinition
    decision_time: datetime
    value: T
    latest_source_timestamp_used: datetime

    _utc = field_validator("decision_time", "latest_source_timestamp_used")(ensure_utc)

    @model_validator(mode="after")
    def no_future_source(self) -> FeatureResult[T]:
        if self.latest_source_timestamp_used > self.decision_time:
            raise ValueError("feature leakage: source timestamp exceeds decision time")
        return self


def build_bars(
    records: Iterable[CanonicalMarketRecord], *, interval: timedelta, as_of: datetime
) -> tuple[Bar, ...]:
    """Build interval-end-labelled bars from available records; never invent a missing bar."""
    if interval <= timedelta(0):
        raise ValueError("interval must be positive")
    as_of = ensure_utc(as_of)
    eligible = sorted(
        (record for record in records if record.available_at <= as_of), key=lambda r: r.event_time
    )
    buckets: dict[datetime, list[CanonicalMarketRecord]] = {}
    seconds = int(interval.total_seconds())
    for record in eligible:
        epoch = int(record.event_time.timestamp())
        end = datetime.fromtimestamp((epoch // seconds + 1) * seconds, tz=record.event_time.tzinfo)
        buckets.setdefault(end, []).append(record)
    bars: list[Bar] = []
    for end, bucket in sorted(buckets.items()):
        prices = [record.price for record in bucket]
        volume = sum((record.quantity or Decimal(0) for record in bucket), Decimal(0))
        bars.append(
            Bar(
                start_time=end - interval,
                end_time=end,
                label_time=end,
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=prices[-1],
                volume=volume,
                complete=end <= as_of,
                latest_source_timestamp_used=max(r.available_at for r in bucket),
            )
        )
    return tuple(bars)


def asof_join[T](
    left_decision_times: Sequence[datetime],
    right: Sequence[tuple[datetime, T]],
    *,
    max_staleness: timedelta,
) -> tuple[T | None, ...]:
    """Join only right observations published by each decision time; stale values become absent."""
    if max_staleness < timedelta(0):
        raise ValueError("max_staleness must be non-negative")
    ordered = sorted(((ensure_utc(at), value) for at, value in right), key=lambda row: row[0])
    index = 0
    latest: tuple[datetime, T] | None = None
    output: list[T | None] = []
    for decision_time in left_decision_times:
        decision_time = ensure_utc(decision_time)
        while index < len(ordered) and ordered[index][0] <= decision_time:
            latest = ordered[index]
            index += 1
        output.append(
            None if latest is None or decision_time - latest[0] > max_staleness else latest[1]
        )
    return tuple(output)
