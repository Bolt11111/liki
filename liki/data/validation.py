"""Deterministic data validation, gap detection, and promotion quarantine."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, field_validator

from .models import CanonicalMarketRecord, QualityStatus, ensure_utc


class FindingKind(StrEnum):
    GAP = "gap"
    DUPLICATE = "duplicate"
    BAD_TICK = "bad_tick"
    UNCERTAIN = "uncertain"
    LOOKAHEAD = "lookahead"
    STALE = "stale"
    SOURCE_COMPROMISE = "source_compromise"
    PROVIDER_DISAGREEMENT = "provider_disagreement"


class ValidationFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: FindingKind
    severity: QualityStatus
    reason: str
    at: datetime | None = None
    raw_payload_hashes: tuple[str, ...] = ()

    _utc = field_validator("at")(ensure_utc)


class DataQualityError(RuntimeError):
    """Raised when promotion-sensitive research receives failed/quarantined data."""


class DatasetValidator:
    def __init__(self, *, max_gap: timedelta, max_staleness: timedelta) -> None:
        if max_gap <= timedelta(0) or max_staleness < timedelta(0):
            raise ValueError("gap and staleness policies must be non-negative")
        self.max_gap = max_gap
        self.max_staleness = max_staleness

    def validate(
        self, records: Iterable[CanonicalMarketRecord], *, decision_time: datetime | None = None
    ) -> tuple[ValidationFinding, ...]:
        ordered = sorted(records, key=lambda record: record.event_time)
        findings: list[ValidationFinding] = []
        seen: set[tuple[datetime, Decimal, Decimal | None, str]] = set()
        previous: CanonicalMarketRecord | None = None
        for record in ordered:
            key = (record.event_time, record.price, record.quantity, record.price_kind)
            if key in seen:
                findings.append(
                    ValidationFinding(
                        kind=FindingKind.DUPLICATE,
                        severity=QualityStatus.WARN,
                        reason="exact duplicate canonical record",
                        at=record.event_time,
                        raw_payload_hashes=(record.raw_payload_hash,),
                    )
                )
            seen.add(key)
            if previous and record.event_time - previous.event_time > self.max_gap:
                findings.append(
                    ValidationFinding(
                        kind=FindingKind.GAP,
                        severity=QualityStatus.FAIL,
                        reason=f"gap exceeds declared maximum {self.max_gap}",
                        at=previous.event_time,
                        raw_payload_hashes=(previous.raw_payload_hash, record.raw_payload_hash),
                    )
                )
            if decision_time and record.available_at > ensure_utc(decision_time):
                findings.append(
                    ValidationFinding(
                        kind=FindingKind.LOOKAHEAD,
                        severity=QualityStatus.FAIL,
                        reason="record was not available at simulated decision time",
                        at=record.available_at,
                        raw_payload_hashes=(record.raw_payload_hash,),
                    )
                )
            previous = record
        if decision_time and ordered:
            age = ensure_utc(decision_time) - ordered[-1].available_at
            if age > self.max_staleness:
                findings.append(
                    ValidationFinding(
                        kind=FindingKind.STALE,
                        severity=QualityStatus.FAIL,
                        reason=f"latest source is stale by {age}",
                        at=ordered[-1].available_at,
                        raw_payload_hashes=(ordered[-1].raw_payload_hash,),
                    )
                )
        return tuple(findings)

    @staticmethod
    def promotion_status(findings: Iterable[ValidationFinding]) -> QualityStatus:
        findings = tuple(findings)
        if any(finding.kind == FindingKind.SOURCE_COMPROMISE for finding in findings):
            return QualityStatus.QUARANTINED
        if any(finding.severity == QualityStatus.FAIL for finding in findings):
            return QualityStatus.FAIL
        if findings:
            return QualityStatus.WARN
        return QualityStatus.PASS

    @classmethod
    def require_usable(cls, findings: Iterable[ValidationFinding]) -> None:
        status = cls.promotion_status(findings)
        if status in {QualityStatus.FAIL, QualityStatus.QUARANTINED}:
            raise DataQualityError(f"dataset not eligible for research: {status}")

    @staticmethod
    def quarantine(
        reason: str, *, at: datetime, raw_payload_hashes: tuple[str, ...]
    ) -> ValidationFinding:
        """Suspected source compromise is retained but cannot enter promotion-sensitive research."""
        if not raw_payload_hashes:
            raise ValueError("quarantine requires preserved raw payload provenance")
        return ValidationFinding(
            kind=FindingKind.SOURCE_COMPROMISE,
            severity=QualityStatus.QUARANTINED,
            reason=reason,
            at=at,
            raw_payload_hashes=raw_payload_hashes,
        )
