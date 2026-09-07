from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from liki.data import (
    DatasetManifest,
    FidelityTier,
    InstrumentSpec,
    LifecycleEvent,
    LifecycleEventKind,
    QualityStatus,
    RawPayload,
)
from liki.data.validation import DataQualityError
from liki.data_service import DataService
from liki.core import DomainError, uid


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def payload() -> RawPayload:
    return RawPayload.from_bytes(
        provider="binance",
        uri="https://api.binance.com/api/v3/exchangeInfo",
        content=b'{"symbols":[]}',
        retrieved_at=NOW,
    )


def manifest(raw: RawPayload, snapshot_id: str) -> DatasetManifest:
    return DatasetManifest(
        dataset_snapshot_id=snapshot_id,
        provider="binance",
        venue="binance",
        instrument="BTCUSDT",
        instrument_type="spot",
        start_time=NOW - timedelta(hours=1),
        end_time=NOW,
        as_of_time=NOW,
        fetched_at=NOW,
        candle_semantics="UTC half-open intervals",
        timestamp_semantics="interval end",
        delisting_policy="effective-dated symbol master",
        survivorship_policy="point-in-time universe",
        freshness_sec=0,
        freshness_sla_sec=60,
        schema_hash="sha256:" + "1" * 64,
        content_hash="sha256:" + "2" * 64,
        quality_status=QualityStatus.PASS,
        raw_payload_hashes=(raw.content_hash,),
        fidelity_tier=FidelityTier.F0_BAR,
    )


def instrument(
    raw: RawPayload, instrument_id: str, effective_from: datetime, approximation: str | None = None
) -> InstrumentSpec:
    return InstrumentSpec(
        instrument_id=instrument_id,
        venue="binance",
        venue_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        contract_type="spot",
        effective_from=effective_from,
        multiplier=Decimal("1"),
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.00001"),
        status="TRADING",
        historical_approximation=approximation,
        raw_payload_hash=raw.content_hash,
    )


def test_dataset_persistence_writes_raw_artifacts_transition_and_manifest(store, credentials):
    raw = payload()
    service = DataService(store)
    snapshot_id, operation_key = uid("SNAP"), uid("OP")
    snapshot = manifest(raw, snapshot_id)
    artifact_id = service.persist_dataset(
        credentials["data"],
        snapshot,
        (raw,),
        operation_key=operation_key,
        task_id="data-test",
        policy_version="v1",
    )
    assert artifact_id == service.persist_dataset(
        credentials["data"],
        snapshot,
        (raw,),
        operation_key=operation_key,
        task_id="data-test",
        policy_version="v1",
    )
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT count(*) AS n FROM data_raw_payloads").fetchone()["n"] >= 1
        row = conn.execute(
            "SELECT * FROM dataset_manifests WHERE dataset_snapshot_id=%s", (snapshot_id,)
        ).fetchone()
        assert row["manifest_artifact_id"] == artifact_id
        event = conn.execute(
            "SELECT event_type FROM event_log WHERE event_id=%s", (row["event_id"],)
        ).fetchone()
        assert event["event_type"] == "DATASET_MANIFEST_PERSISTED"
        raw_artifact = conn.execute(
            "SELECT a.content FROM data_raw_payloads r JOIN artifacts a ON a.artifact_id=r.artifact_id "
            "WHERE r.content_hash=%s ORDER BY r.raw_payload_id DESC LIMIT 1",
            (raw.content_hash,),
        ).fetchone()
        assert raw_artifact["content"]["payload_base64"] == "eyJzeW1ib2xzIjpbXX0="


def test_current_metadata_cannot_silently_become_historical_and_missing_history_is_unknown(
    store, credentials
):
    raw = payload()
    service = DataService(store)
    instrument_id = uid("INSTRUMENT")
    with pytest.raises(DataQualityError, match="current metadata"):
        service.persist_instrument_specification(
            credentials["data"],
            instrument(raw, instrument_id, NOW - timedelta(days=1)),
            raw,
            operation_key=uid("OP"),
            task_id="data-test",
            policy_version="v1",
        )
    unknown = service.historical_specification(
        credentials["data"], instrument_id, NOW - timedelta(days=1)
    )
    assert unknown.state == "UNKNOWN" and unknown.specification is None


def test_effective_dated_specification_is_retrievable_only_at_its_recorded_time(store, credentials):
    raw = payload()
    service = DataService(store)
    instrument_id = uid("INSTRUMENT")
    specification = instrument(raw, instrument_id, NOW)
    operation_key = uid("OP")
    artifact_id = service.persist_instrument_specification(
        credentials["data"],
        specification,
        raw,
        operation_key=operation_key,
        task_id="data-test",
        policy_version="v1",
    )
    assert artifact_id == service.persist_instrument_specification(
        credentials["data"],
        specification,
        raw,
        operation_key=operation_key,
        task_id="data-test",
        policy_version="v1",
    )
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        service.persist_instrument_specification(
            credentials["data"],
            specification.model_copy(update={"status": "HALTED"}),
            raw,
            operation_key=operation_key,
            task_id="data-test",
            policy_version="v1",
        )
    assert (
        service.historical_specification(credentials["data"], instrument_id, NOW).state == "VALUE"
    )
    assert (
        service.historical_specification(
            credentials["data"], instrument_id, NOW - timedelta(seconds=1)
        ).state
        == "UNKNOWN"
    )


def test_dataset_write_requires_data_capability_and_conflicting_replay_is_atomic(
    store, credentials
):
    raw = payload()
    service = DataService(store)
    snapshot_id, operation_key = uid("SNAP"), uid("OP")
    snapshot = manifest(raw, snapshot_id)
    with pytest.raises(DomainError, match="capability"):
        service.persist_dataset(
            credentials["research"],
            snapshot,
            (raw,),
            operation_key=operation_key,
            task_id="data-test",
            policy_version="v1",
        )
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM dataset_manifests WHERE dataset_snapshot_id=%s",
                (snapshot_id,),
            ).fetchone()["n"]
            == 0
        )

    artifact_id = service.persist_dataset(
        credentials["data"],
        snapshot,
        (raw,),
        operation_key=operation_key,
        task_id="data-test",
        policy_version="v1",
    )
    changed = snapshot.model_copy(update={"content_hash": "sha256:" + "3" * 64})
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        service.persist_dataset(
            credentials["data"],
            changed,
            (raw,),
            operation_key=operation_key,
            task_id="data-test",
            policy_version="v1",
        )
    with store.transaction(credentials["auditor"]) as (conn, _):
        row = conn.execute(
            "SELECT manifest_artifact_id, content_hash FROM dataset_manifests WHERE dataset_snapshot_id=%s",
            (snapshot_id,),
        ).fetchone()
        assert row == {"manifest_artifact_id": artifact_id, "content_hash": snapshot.content_hash}
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM artifacts WHERE schema_name='data/dataset-manifest-v1' "
                "AND content->>'content_hash'=%s",
                (changed.content_hash,),
            ).fetchone()["n"]
            == 0
        )


def test_lifecycle_write_is_content_bound_and_idempotent(store, credentials):
    raw = payload()
    service = DataService(store)
    event = LifecycleEvent(
        instrument_id=uid("INSTRUMENT"),
        kind=LifecycleEventKind.SYMBOL_CHANGE,
        effective_at=NOW,
        details={"old_symbol": "BTCUSDT", "new_symbol": "XBTUSDT"},
        raw_payload_hash=raw.content_hash,
    )
    operation_key = uid("OP")
    first = service.persist_lifecycle_event(
        credentials["data"],
        event,
        raw,
        operation_key=operation_key,
        task_id="data-test",
        policy_version="v1",
    )
    assert first == service.persist_lifecycle_event(
        credentials["data"],
        event,
        raw,
        operation_key=operation_key,
        task_id="data-test",
        policy_version="v1",
    )
    changed = event.model_copy(
        update={"details": {"old_symbol": "BTCUSDT", "new_symbol": "BTC-NEW"}}
    )
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        service.persist_lifecycle_event(
            credentials["data"],
            changed,
            raw,
            operation_key=operation_key,
            task_id="data-test",
            policy_version="v1",
        )
