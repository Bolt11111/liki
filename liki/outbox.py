"""Fenced, at-least-once delivery; uncertain external outcomes never count as receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import Field

from liki.core import Contract, DomainError, content_hash, uid, utcnow
from liki.store import Credential, Store


class Notification(Contract):
    deduplication_key: str = Field(min_length=1, max_length=200)
    urgency: Literal["CRITICAL", "HIGH", "NORMAL", "DIGEST"]
    classification: Literal["PUBLIC", "INTERNAL"]
    recipient_ref: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=3400)
    required_action: str | None = Field(default=None, max_length=200)
    deadline_at: datetime | None = None
    object_id: str | None = None


@dataclass(frozen=True)
class DeliveryLease:
    outbox_id: str
    lease_token: str
    topic: str
    payload: dict
    attempt: int


class Outbox:
    def __init__(self, store: Store):
        self.store = store

    def notify(self, conn, actor, notification: Notification) -> str:
        actor.require("notification")
        conn.execute("SELECT pg_advisory_xact_lock(71403218)")
        if notification.deadline_at and notification.deadline_at.tzinfo is None:
            raise DomainError("UTC_REQUIRED")
        digest = content_hash(notification)
        previous = conn.execute("SELECT * FROM notification_records WHERE deduplication_key=%s",
                                (notification.deduplication_key,)).fetchone()
        if previous:
            if previous["content_hash"] != digest:
                raise DomainError("IDEMPOTENCY_CONFLICT")
            return previous["notification_id"]
        notification_id = uid("NTF")
        event = self.store.transition(conn, actor, capability="notification", kind="notification",
            aggregate_id=notification_id, expected_version=0,
            state={"status": "PENDING", "notification_hash": digest, "urgency": notification.urgency},
            event_type="NOTIFICATION_QUEUED", operation_key="notify:" + notification.deduplication_key,
            task_id=notification.object_id or notification_id, policy_version="notification-v1")
        conn.execute("INSERT INTO notification_records(notification_id,deduplication_key,content_hash,"
            "urgency,classification,recipient_ref,title,message,required_action,deadline_at,object_id,event_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (notification_id, notification.deduplication_key, digest, notification.urgency,
             notification.classification, notification.recipient_ref, notification.title,
             notification.message, notification.required_action, notification.deadline_at,
             notification.object_id, event["event_id"]))
        conn.execute("INSERT INTO transactional_outbox(outbox_id,event_id,topic,payload) VALUES(%s,%s,%s,%s)",
            (uid("OUT"), event["event_id"], "telegram.notification", Jsonb({"notification_id": notification_id})))
        return notification_id

    def claim(self, credential: Credential, topics: tuple[str, ...], *, lease_seconds: int = 60) -> DeliveryLease | None:
        if not topics or not 1 <= lease_seconds <= 300:
            raise DomainError("INVALID_DELIVERY_LEASE")
        with self.store.transaction(credential) as (conn, actor):
            actor.require("notification")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            # A lost sender may have delivered. Reconcile instead of blind re-send.
            expired = conn.execute("SELECT * FROM transactional_outbox WHERE topic=ANY(%s) "
                "AND status='LEASED' AND lease_expires_at<=now() FOR UPDATE", (list(topics),)).fetchall()
            for row in expired:
                self._transition(conn, actor, row, "QUARANTINED", "DELIVERY_LEASE_EXPIRED", {})
                conn.execute("UPDATE transactional_outbox SET status='QUARANTINED' WHERE outbox_id=%s",
                             (row["outbox_id"],))
            row = conn.execute("SELECT * FROM transactional_outbox WHERE topic=ANY(%s) "
                "AND status='PENDING' AND available_at<=now() ORDER BY available_at,outbox_id "
                "FOR UPDATE SKIP LOCKED LIMIT 1", (list(topics),)).fetchone()
            if not row:
                return None
            fence = uid("DELIVERY")
            expires = utcnow() + timedelta(seconds=lease_seconds)
            self._transition(conn, actor, row, "LEASED", "DELIVERY_STARTED",
                             {"lease_token": fence, "worker_id": actor.principal_id})
            conn.execute("UPDATE transactional_outbox SET status='LEASED',lease_token=%s,lease_expires_at=%s,"
                "attempts=attempts+1 WHERE outbox_id=%s", (fence, expires, row["outbox_id"]))
            return DeliveryLease(row["outbox_id"], fence, row["topic"], row["payload"], row["attempts"] + 1)

    def _transition(self, conn, actor, row: dict, status: str, event_type: str, metadata: dict) -> dict:
        current = self.store.state(conn, "outbox_delivery", row["outbox_id"])
        return self.store.transition(conn, actor, capability="notification", kind="outbox_delivery",
            aggregate_id=row["outbox_id"], expected_version=current["version"] if current else 0,
            state={"status": status, "outbox_id": row["outbox_id"], "source_event_id": row["event_id"],
                   "attempts": row["attempts"], **metadata}, event_type=event_type,
            operation_key=uid("DELIVERY-OP"), task_id=row["outbox_id"], policy_version="delivery-v1")

    def finish(self, credential: Credential, lease: DeliveryLease, *, receipt: str | None = None,
               failure: Literal["TRANSIENT", "PERMANENT", "UNKNOWN_DELIVERY"] | None = None,
               retry_after: int = 1) -> str:
        if (receipt is None) == (failure is None) or receipt == "" or not 1 <= retry_after <= 86400:
            raise DomainError("INVALID_DELIVERY_RESULT")
        with self.store.transaction(credential) as (conn, actor):
            actor.require("notification")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            row = conn.execute("SELECT * FROM transactional_outbox WHERE outbox_id=%s",
                               (lease.outbox_id,)).fetchone()
            if not row or row["lease_token"] != lease.lease_token:
                raise DomainError("STALE_DELIVERY_LEASE")
            current = self.store.state(conn, "outbox_delivery", row["outbox_id"])
            if row["status"] != "LEASED" and (not current or not current["state"].get("result_hash")):
                raise DomainError("STALE_DELIVERY_LEASE")
            if current is None or current["state"].get("worker_id") != actor.principal_id:
                raise DomainError("FORBIDDEN")
            row = conn.execute("SELECT * FROM transactional_outbox WHERE outbox_id=%s FOR UPDATE",
                               (lease.outbox_id,)).fetchone()
            if not row or row["lease_token"] != lease.lease_token:
                raise DomainError("STALE_DELIVERY_LEASE")
            result_hash = content_hash({"receipt": receipt, "failure": failure, "retry_after": retry_after})
            if row["status"] != "LEASED" and current["state"].get("result_hash"):
                if current["state"]["result_hash"] == result_hash:
                    return row["status"]
                raise DomainError("IDEMPOTENCY_CONFLICT")
            if row["status"] != "LEASED" or row["lease_expires_at"] <= utcnow():
                raise DomainError("STALE_DELIVERY_LEASE")
            status = "DELIVERED" if receipt else "PENDING" if failure == "TRANSIENT" and row["attempts"] < 5 else "QUARANTINED"
            event = self._transition(conn, actor, row, status, "DELIVERY_" + status,
                                     {"receipt": receipt, "failure": failure, "result_hash": result_hash,
                                      "worker_id": actor.principal_id})
            conn.execute("UPDATE transactional_outbox SET status=%s,available_at=%s,delivered_at=%s "
                "WHERE outbox_id=%s", (status, utcnow() + timedelta(seconds=max(retry_after, 2 ** row["attempts"])),
                                       utcnow() if receipt else None, lease.outbox_id))
            if receipt and row["topic"] == "telegram.notification":
                conn.execute("INSERT INTO notification_deliveries VALUES(%s,%s,%s,%s,%s)",
                    (row["payload"]["notification_id"], lease.outbox_id, receipt, utcnow(), event["event_id"]))
            return status
