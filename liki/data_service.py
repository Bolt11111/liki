"""Durable data artifact persistence over the core append-only Store."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb

from liki.core import DomainError, uid
from liki.data.instruments import InstrumentSpec, LifecycleEvent
from liki.data.models import DatasetManifest, RawPayload, ensure_utc
from liki.data.validation import DataQualityError
from liki.store import Credential, Identity, Store


@dataclass(frozen=True)
class HistoricalSpecificationResolution:
    state: str
    specification: InstrumentSpec | None
    reason: str | None = None


class DataService:
    """Writes raw evidence before normalized metadata and transitions in one transaction."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def _persist_raw_payload(
        self, conn: psycopg.Connection, actor: Identity, payload: RawPayload, policy_version: str
    ) -> tuple[str, str]:
        actor.require("data")
        if not payload.payload_bytes:
            raise DataQualityError("raw payload bytes are required for durable source snapshots")
        observed = RawPayload.from_bytes(
            provider=payload.provider,
            uri=payload.uri,
            content=payload.payload_bytes,
            retrieved_at=payload.retrieved_at,
            content_type=payload.content_type,
            provider_revision_id=payload.provider_revision_id,
            transport_metadata=payload.transport_metadata,
        )
        if observed.content_hash != payload.content_hash:
            raise DataQualityError("raw payload content hash does not match supplied bytes")
        artifact_id = self.store.put_artifact(
            conn,
            actor,
            {
                "raw_payload": payload.model_dump(mode="json"),
                "payload_base64": base64.b64encode(payload.payload_bytes).decode("ascii"),
            },
            schema_name="data/raw-payload-v1",
            classification="INTERNAL",
            policy_version=policy_version,
        )
        existing = conn.execute(
            "SELECT raw_payload_id FROM data_raw_payloads WHERE artifact_id=%s AND provider=%s "
            "AND source_uri=%s AND retrieved_at=%s",
            (artifact_id, payload.provider, payload.uri, payload.retrieved_at),
        ).fetchone()
        if existing:
            return cast(dict[str, str], existing)["raw_payload_id"], artifact_id
        raw_payload_id = uid("RAW")
        conn.execute(
            "INSERT INTO data_raw_payloads(raw_payload_id,artifact_id,content_hash,provider,source_uri,"
            "retrieved_at,provider_revision_id,transport_metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                raw_payload_id,
                artifact_id,
                payload.content_hash,
                payload.provider,
                payload.uri,
                payload.retrieved_at,
                payload.provider_revision_id,
                Jsonb(payload.transport_metadata),
            ),
        )
        return raw_payload_id, artifact_id

    def persist_dataset(
        self,
        credential: Credential,
        manifest: DatasetManifest,
        raw_payloads: tuple[RawPayload, ...],
        *,
        operation_key: str,
        task_id: str,
        policy_version: str,
    ) -> str:
        """Persist raw responses, then immutable manifest and audit transition atomically."""
        if not raw_payloads:
            raise DataQualityError("dataset snapshots require raw provider payloads")
        if set(manifest.raw_payload_hashes) - {payload.content_hash for payload in raw_payloads}:
            raise DataQualityError(
                "manifest raw payload pointers do not match supplied source snapshots"
            )
        with self.store.transaction(credential) as (conn, actor):
            raw_rows = [
                self._persist_raw_payload(conn, actor, payload, policy_version)
                for payload in raw_payloads
            ]
            manifest_artifact_id = self.store.put_artifact(
                conn,
                actor,
                manifest.model_dump(mode="json"),
                schema_name="data/dataset-manifest-v1",
                classification="INTERNAL",
                policy_version=policy_version,
            )
            event = self.store.transition(
                conn,
                actor,
                capability="data",
                kind="dataset_snapshot",
                aggregate_id=manifest.dataset_snapshot_id,
                expected_version=0,
                state={
                    "dataset_snapshot_id": manifest.dataset_snapshot_id,
                    "quality_status": manifest.quality_status,
                    "content_hash": manifest.content_hash,
                },
                event_type="DATASET_MANIFEST_PERSISTED",
                operation_key=operation_key,
                task_id=task_id,
                policy_version=policy_version,
                artifact_ids=(manifest_artifact_id,)
                + tuple(artifact_id for _, artifact_id in raw_rows),
                metadata={"raw_payload_hashes": manifest.raw_payload_hashes},
                topic="data.snapshot.persisted",
            )
            existing = conn.execute(
                "SELECT manifest_artifact_id FROM dataset_manifests WHERE dataset_snapshot_id=%s",
                (manifest.dataset_snapshot_id,),
            ).fetchone()
            if (
                existing
                and cast(dict[str, str], existing)["manifest_artifact_id"] != manifest_artifact_id
            ):
                raise DomainError("DATASET_SNAPSHOT_CONFLICT")
            if not existing:
                conn.execute(
                    "INSERT INTO dataset_manifests(dataset_snapshot_id,manifest_artifact_id,content_hash,"
                    "quality_status,raw_payload_hashes,event_id) VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        manifest.dataset_snapshot_id,
                        manifest_artifact_id,
                        manifest.content_hash,
                        manifest.quality_status,
                        list(manifest.raw_payload_hashes),
                        event["event_id"],
                    ),
                )
            return manifest_artifact_id

    def persist_instrument_specification(
        self,
        credential: Credential,
        specification: InstrumentSpec,
        source_payload: RawPayload,
        *,
        operation_key: str,
        task_id: str,
        policy_version: str,
    ) -> str:
        """Refuse to project a current exchange response backwards without an explicit approximation."""
        if specification.raw_payload_hash != source_payload.content_hash:
            raise DataQualityError(
                "instrument specification must point to its supplied raw payload"
            )
        if (
            specification.effective_from < source_payload.retrieved_at
            and not specification.historical_approximation
        ):
            raise DataQualityError(
                "current metadata cannot be assigned to historical effective dates"
            )
        with self.store.transaction(credential) as (conn, actor):
            raw_payload_id, raw_artifact_id = self._persist_raw_payload(
                conn, actor, source_payload, policy_version
            )
            artifact_id = self.store.put_artifact(
                conn,
                actor,
                specification.model_dump(mode="json"),
                schema_name="data/instrument-specification-v1",
                classification="INTERNAL",
                policy_version=policy_version,
            )
            event = self.store.transition(
                conn,
                actor,
                capability="data",
                kind="instrument_specification",
                aggregate_id=artifact_id,
                expected_version=0,
                state={
                    "instrument_id": specification.instrument_id,
                    "effective_from": specification.effective_from.isoformat(),
                },
                event_type="INSTRUMENT_SPECIFICATION_PERSISTED",
                operation_key=operation_key,
                task_id=task_id,
                policy_version=policy_version,
                artifact_ids=(artifact_id, raw_artifact_id),
                topic="data.instrument.persisted",
            )
            conn.execute(
                "INSERT INTO instrument_specifications(instrument_specification_id,specification_artifact_id,"
                "instrument_id,venue,effective_from,effective_to,source_raw_payload_id,historical_approximation,event_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(specification_artifact_id) DO NOTHING",
                (
                    uid("SPEC"),
                    artifact_id,
                    specification.instrument_id,
                    specification.venue,
                    specification.effective_from,
                    specification.effective_to,
                    raw_payload_id,
                    specification.historical_approximation,
                    event["event_id"],
                ),
            )
            return artifact_id

    def historical_specification(
        self, credential: Credential, instrument_id: str, at: datetime
    ) -> HistoricalSpecificationResolution:
        """Return explicit UNKNOWN when no effective-dated source exists; never fall back to live metadata."""
        at = ensure_utc(at)
        with self.store.transaction(credential) as (conn, actor):
            actor.require("read")
            rows = cast(
                list[dict[str, Any]],
                conn.execute(
                    "SELECT a.content FROM instrument_specifications s JOIN artifacts a ON a.artifact_id=s.specification_artifact_id "
                    "WHERE s.instrument_id=%s AND s.effective_from<=%s AND (s.effective_to IS NULL OR s.effective_to>%s)",
                    (instrument_id, at, at),
                ).fetchall(),
            )
            if len(rows) != 1:
                return HistoricalSpecificationResolution(
                    "UNKNOWN", None, "no unambiguous effective-dated specification"
                )
            return HistoricalSpecificationResolution(
                "VALUE", InstrumentSpec.model_validate(rows[0]["content"])
            )

    def persist_lifecycle_event(
        self,
        credential: Credential,
        lifecycle_event: LifecycleEvent,
        source_payload: RawPayload,
        *,
        operation_key: str,
        task_id: str,
        policy_version: str,
    ) -> str:
        if lifecycle_event.raw_payload_hash != source_payload.content_hash:
            raise DataQualityError("lifecycle event must point to its supplied raw payload")
        with self.store.transaction(credential) as (conn, actor):
            raw_payload_id, raw_artifact_id = self._persist_raw_payload(
                conn, actor, source_payload, policy_version
            )
            artifact_id = self.store.put_artifact(
                conn,
                actor,
                lifecycle_event.model_dump(mode="json"),
                schema_name="data/instrument-lifecycle-v1",
                classification="INTERNAL",
                policy_version=policy_version,
            )
            event = self.store.transition(
                conn,
                actor,
                capability="data",
                kind="instrument_lifecycle",
                aggregate_id=artifact_id,
                expected_version=0,
                state={
                    "instrument_id": lifecycle_event.instrument_id,
                    "effective_at": lifecycle_event.effective_at.isoformat(),
                },
                event_type="INSTRUMENT_LIFECYCLE_PERSISTED",
                operation_key=operation_key,
                task_id=task_id,
                policy_version=policy_version,
                artifact_ids=(artifact_id, raw_artifact_id),
                topic="data.lifecycle.persisted",
            )
            conn.execute(
                "INSERT INTO instrument_lifecycle_events(lifecycle_event_id,lifecycle_artifact_id,instrument_id,event_kind,effective_at,source_raw_payload_id,event_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(lifecycle_artifact_id) DO NOTHING",
                (
                    uid("LIF"),
                    artifact_id,
                    lifecycle_event.instrument_id,
                    lifecycle_event.kind,
                    lifecycle_event.effective_at,
                    raw_payload_id,
                    event["event_id"],
                ),
            )
            return artifact_id
