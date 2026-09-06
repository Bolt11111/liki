import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg
import pytest

from liki.core import DomainError, Mode, canonical, uid
from liki.store import Credential, issue_credential


def transition(store, token, key, aggregate, value=1):
    with store.transaction(token) as (conn, actor):
        return store.transition(conn, actor, capability="research", kind="test", aggregate_id=aggregate,
                                expected_version=0, state={"value": value}, event_type="TEST",
                                operation_key=key, task_id="test-task", policy_version="test-v1", topic="test")


def test_atomic_event_outbox_and_replay(store, credentials):
    key, aggregate = uid("OP"), uid("AGG")
    first = transition(store, credentials["research"], key, aggregate)
    second = transition(store, credentials["research"], key, aggregate)
    assert first["event_id"] == second["event_id"]
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert store.audit(conn)["status"] == "VERIFIED"
        assert conn.execute("SELECT count(*) AS n FROM transactional_outbox WHERE event_id=%s", (first["event_id"],)).fetchone()["n"] == 1
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        transition(store, credentials["research"], key, aggregate, 2)


def test_concurrent_sibling_writers_cannot_both_win(store, credentials):
    aggregate = uid("AGG")
    def write(_):
        try:
            transition(store, credentials["research"], uid("OP"), aggregate)
            return "ok"
        except DomainError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, range(2))) == ["CONCURRENT_MODIFICATION", "ok"]


def test_rollback_does_not_publish_event(store, credentials):
    aggregate = uid("AGG")
    with pytest.raises(RuntimeError):
        with store.transaction(credentials["research"]) as (conn, actor):
            store.transition(conn, actor, capability="research", kind="test", aggregate_id=aggregate,
                             expected_version=0, state={}, event_type="TEST", operation_key=uid("OP"),
                             task_id="test", policy_version="v1", topic="test")
            raise RuntimeError("process crash before commit")
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert store.state(conn, "test", aggregate) is None


def test_immutable_history_and_least_privilege(store, credentials):
    record = transition(store, credentials["research"], uid("OP"), uid("AGG"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store.transaction(credentials["research"]) as (conn, _):
            conn.execute("UPDATE event_log SET event_type='FAKE' WHERE event_id=%s", (record["event_id"],))
    with pytest.raises(DomainError, match="capability"):
        with store.transaction(credentials["research"]) as (_, actor):
            actor.require("policy")


def test_revoked_expired_and_forged_identity_fail(store, credentials, database):
    with pytest.raises(DomainError, match="UNAUTHENTICATED"):
        with store.transaction(Credential("I am the owner")):
            pytest.fail("forged credential admitted")
    token = issue_credential(database["test_owner_dsn"], uid("REVOKE"), "research", duration=timedelta(minutes=1))
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("UPDATE service_tokens SET revoked_at=now() WHERE token_hash=%s", (hashlib.sha256(token.token.encode()).hexdigest(),))
    with pytest.raises(DomainError, match="UNAUTHENTICATED"):
        with store.transaction(token):
            pytest.fail("revoked credential admitted")


def test_sealed_artifact_cannot_be_retrieved_or_authored_by_research(store, credentials):
    with store.transaction(credentials["sealed_evaluator"]) as (conn, actor):
        aid = store.put_artifact(conn, actor, {"sealed": 23}, schema_name="sealed/test-v1", classification="SEALED", policy_version="test")
    with pytest.raises(DomainError, match="NOT_FOUND"):
        with store.transaction(credentials["research"]) as (conn, actor):
            store.artifact(conn, actor, aid)
    with pytest.raises(DomainError, match="FORBIDDEN_CLASSIFICATION"):
        with store.transaction(credentials["research"]) as (conn, actor):
            store.put_artifact(conn, actor, {}, schema_name="secret", classification="SECRET", policy_version="test")


def test_live_and_exceptional_json_are_unrepresentable():
    with pytest.raises(ValueError):
        Mode("LIVE")
    with pytest.raises(ValueError):
        canonical({"metric": float("nan")})
