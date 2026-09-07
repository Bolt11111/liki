import psycopg
import pytest
from psycopg.types.json import Jsonb

from liki.core import DomainError, content_hash, uid


def test_database_login_without_service_identity_has_no_data_visibility(store, credentials, database):
    with store.transaction(credentials["research"]) as (conn, actor):
        aid = store.put_artifact(conn, actor, {"internal": "fixture"}, schema_name="test", classification="INTERNAL", policy_version="v1")
    with psycopg.connect(database["test_app_dsn"]) as conn:
        assert conn.execute("SELECT artifact_id FROM artifacts WHERE artifact_id=%s", (aid,)).fetchone() is None
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT token_hash FROM service_tokens")


def test_direct_sql_cannot_spoof_evidence_producer_or_read_sealed(store, credentials):
    with store.transaction(credentials["sealed_evaluator"]) as (conn, actor):
        sealed = store.put_artifact(conn, actor, {"raw_sealed": "never exposed"}, schema_name="sealed", classification="SEALED", policy_version="v1")
        evaluator_id = actor.principal_id
    with store.transaction(credentials["research"]) as (conn, actor):
        assert conn.execute("SELECT content FROM artifacts WHERE artifact_id=%s", (sealed,)).fetchone() is None
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store.transaction(credentials["research"]) as (conn, actor):
            conn.execute("INSERT INTO artifacts(artifact_id,content_hash,schema_name,classification,producer_id,environment_fingerprint,policy_version,content) "
                         "VALUES(%s,%s,'fake','INTERNAL',%s,'fake','fake',%s)",
                         (uid("FORGED"), content_hash({}), evaluator_id, Jsonb({})))


def test_research_cannot_mutate_paper_or_policy_aggregate_with_raw_sql(store, credentials):
    for aggregate_type in ("paper_run", "candidate", "policy_version", "governance_proposal"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with store.transaction(credentials["research"]) as (conn, _):
                conn.execute("INSERT INTO aggregates VALUES(%s,%s,1,%s)",
                             (aggregate_type, uid("FORGED"), Jsonb({"status": "PROMOTED"})))
    with pytest.raises(DomainError, match="capability"):
        with store.transaction(credentials["evaluator"]) as (_, actor):
            actor.require("research")
