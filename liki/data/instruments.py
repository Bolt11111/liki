"""Effective-dated symbol master and lifecycle-aware historical universes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import ensure_optional_utc, ensure_utc


class LifecycleEventKind(StrEnum):
    LISTING = "listing"
    DELISTING = "delisting"
    SUSPENSION = "suspension"
    RELISTING = "relisting"
    SYMBOL_CHANGE = "symbol_change"
    REDENOMINATION = "redenomination"
    MIGRATION = "migration"
    EXPIRY = "expiry"
    SETTLEMENT = "settlement"
    RULE_CHANGE = "rule_change"


class LifecycleEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    kind: LifecycleEventKind
    effective_at: datetime
    details: dict[str, str] = Field(default_factory=dict)
    conversion_ratio: Decimal | None = Field(default=None, gt=0)
    raw_payload_hash: str

    _utc = field_validator("effective_at")(ensure_utc)


class InstrumentSpec(BaseModel):
    """One version of an exchange instrument valid over a half-open time range."""

    model_config = ConfigDict(frozen=True)

    instrument_id: str
    venue: str
    venue_symbol: str
    base_asset: str
    quote_asset: str
    contract_type: str
    effective_from: datetime
    effective_to: datetime | None = None
    expiry_at: datetime | None = None
    multiplier: Decimal = Field(gt=0)
    settlement_asset: str | None = None
    margin_asset: str | None = None
    tick_size: Decimal = Field(gt=0)
    lot_size: Decimal = Field(gt=0)
    min_notional: Decimal | None = Field(default=None, gt=0)
    status: str
    historical_approximation: str | None = None
    raw_payload_hash: str

    _utc = field_validator("effective_from")(ensure_utc)
    _optional_utc = field_validator("effective_to", "expiry_at")(ensure_optional_utc)

    @model_validator(mode="after")
    def valid_range(self) -> InstrumentSpec:
        if self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must follow effective_from")
        return self

    def is_effective_at(self, at: datetime) -> bool:
        at = ensure_utc(at)
        return self.effective_from <= at and (self.effective_to is None or at < self.effective_to)


class SymbolMaster:
    """In-memory deterministic view; persistence is supplied by the parent ledger."""

    def __init__(
        self,
        specifications: list[InstrumentSpec],
        lifecycle_events: list[LifecycleEvent] | None = None,
    ) -> None:
        self.specifications = tuple(specifications)
        self.lifecycle_events = tuple(lifecycle_events or ())
        self._validate_non_overlapping()

    def _validate_non_overlapping(self) -> None:
        grouped: dict[str, list[InstrumentSpec]] = {}
        for spec in self.specifications:
            grouped.setdefault(spec.instrument_id, []).append(spec)
        for instrument_specs in grouped.values():
            ordered = sorted(instrument_specs, key=lambda spec: spec.effective_from)
            for previous, current in zip(ordered, ordered[1:], strict=False):
                if previous.effective_to is None or previous.effective_to > current.effective_from:
                    raise ValueError("overlapping effective-dated instrument specifications")

    def specification_at(self, instrument_id: str, at: datetime) -> InstrumentSpec:
        matches = [
            spec
            for spec in self.specifications
            if spec.instrument_id == instrument_id and spec.is_effective_at(at)
        ]
        if len(matches) != 1:
            raise LookupError(
                f"no unambiguous instrument specification for {instrument_id} at {at}"
            )
        return matches[0]

    def available_universe(
        self, at: datetime, *, venue: str | None = None
    ) -> tuple[InstrumentSpec, ...]:
        return tuple(
            spec
            for spec in self.specifications
            if spec.is_effective_at(at)
            and spec.status == "TRADING"
            and (venue is None or spec.venue == venue)
        )
