from datetime import timedelta

import psycopg
import pytest

from liki.core import DomainError, uid, utcnow
from liki.outbox import Notification, Outbox


def queued(store, credentials, **updates):
    notification = Notification(deduplication_key=uid("DEDUPE"), urgency="HIGH", classification="INTERNAL",
                                recipient_ref="owner", title="Test fixture", message="Test-only delivery", **updates)
    outbox = Outbox(store)
    with store.transaction(credentials["owner"]) as (conn, actor):
        nid = outbox.notify(conn, actor, notification)
        assert outbox.notify(conn, actor, notification) == nid
    return outbox, notification, nid


def claim_own(outbox, credentials, database, notification_id):
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("UPDATE transactional_outbox SET available_at=now()+interval '1 day' WHERE "
                     "topic='telegram.notification' AND payload->>'notification_id'<>%s", (notification_id,))
    return outbox.claim(credentials["scheduler"], ("telegram.notification",))


def test_delivery_commit_receipt_and_idempotency(store, credentials, database):
    outbox, notification, nid = queued(store, credentials)
    lease = claim_own(outbox, credentials, database, nid)
    assert lease and lease.payload == {"notification_id": nid}
    assert outbox.finish(credentials["scheduler"], lease, receipt="42") == "DELIVERED"
    assert outbox.finish(credentials["scheduler"], lease, receipt="42") == "DELIVERED"
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        outbox.finish(credentials["scheduler"], lease, receipt="43")
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        with store.transaction(credentials["owner"]) as (conn, actor):
            outbox.notify(conn, actor, notification.model_copy(update={"message": "Changed content"}))
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert store.audit(conn)["status"] == "VERIFIED"


def test_unknown_delivery_and_expired_sender_never_claim_success(store, credentials, database):
    outbox, _, nid = queued(store, credentials)
    lease = claim_own(outbox, credentials, database, nid)
    assert lease
    assert outbox.finish(credentials["scheduler"], lease, failure="UNKNOWN_DELIVERY") == "QUARANTINED"
    assert outbox.finish(credentials["scheduler"], lease, failure="UNKNOWN_DELIVERY") == "QUARANTINED"
    outbox, _, nid = queued(store, credentials)
    lease = claim_own(outbox, credentials, database, nid)
    assert lease
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("UPDATE transactional_outbox SET lease_expires_at=%s WHERE outbox_id=%s",
                     (utcnow()-timedelta(seconds=1), lease.outbox_id))
    assert outbox.claim(credentials["scheduler"], ("telegram.notification",)) is None
    with pytest.raises(DomainError, match="STALE_DELIVERY_LEASE"):
        outbox.finish(credentials["scheduler"], lease, receipt="late")


def test_delivery_requires_capability_and_retries_are_bounded(store, credentials, database):
    outbox, _, nid = queued(store, credentials)
    with pytest.raises(DomainError, match="capability"):
        outbox.claim(credentials["research"], ("telegram.notification",))
    for attempt in range(1, 6):
        with psycopg.connect(database["test_owner_dsn"]) as conn:
            conn.execute("UPDATE transactional_outbox SET available_at=now() WHERE payload->>'notification_id'=%s", (nid,))
        lease = claim_own(outbox, credentials, database, nid)
        assert lease and lease.attempt == attempt
        with pytest.raises(DomainError, match="FORBIDDEN"):
            outbox.finish(credentials["owner"], lease, receipt="stolen-lease")
        state = outbox.finish(credentials["scheduler"], lease, failure="TRANSIENT", retry_after=2)
        assert state == ("QUARANTINED" if attempt == 5 else "PENDING")
        assert outbox.finish(credentials["scheduler"], lease, failure="TRANSIENT", retry_after=2) == state
