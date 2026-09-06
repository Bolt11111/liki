from __future__ import annotations

import json
import re
import secrets
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from liki.backup import backup_database
from liki.core import DomainError, uid
from liki.recovery import measure_restore_drill
from liki.store import Store, issue_credential, migrate

_RESTORE_DATABASE_NAME = re.compile(r"liki_restore_[0-9a-f]{16}")
_SOURCE_DATABASE_NAME = re.compile(r"liki_reliability_[0-9a-f]{16}")


def _postgres_sql(database: dict[str, str], statement: str) -> subprocess.CompletedProcess[bytes]:
    port = str(conninfo_to_dict(database["test_owner_dsn"]).get("port") or "5432")
    return subprocess.run(
        ["runuser", "-u", "postgres", "--", "psql", "-A", "-t", "-p", port, "-q", "-v", "ON_ERROR_STOP=1"],
        input=statement.encode(),
        capture_output=True,
        check=False,
    )


def _database_oid(database: dict[str, str], database_name: str) -> str | None:
    result = _postgres_sql(
        database,
        f"SELECT oid FROM pg_database WHERE datname='{database_name}' AND datistemplate=false;",
    )
    if result.returncode:
        return None
    return result.stdout.decode().strip() or None


@pytest.fixture(scope="module")
def database():
    from liki.core import database_config

    runtime = database_config()
    database_name = f"liki_reliability_{secrets.token_hex(8)}"
    assert _SOURCE_DATABASE_NAME.fullmatch(database_name)
    control = {"test_owner_dsn": runtime["test_owner_dsn"]}
    created = _postgres_sql(control, f'CREATE DATABASE "{database_name}" OWNER liki_owner TEMPLATE template0;')
    assert created.returncode == 0
    database_oid = _database_oid(control, database_name)
    assert database_oid is not None
    isolated = {"test_owner_dsn": make_conninfo(runtime["test_owner_dsn"], dbname=database_name),
                "test_app_dsn": make_conninfo(runtime["test_app_dsn"], dbname=database_name)}
    migrate(isolated["test_owner_dsn"])
    try:
        yield isolated
    finally:
        if _database_oid(control, database_name) == database_oid:
            dropped = _postgres_sql(control, f'DROP DATABASE "{database_name}" WITH (FORCE);')
            assert dropped.returncode == 0


@pytest.fixture
def store(database):
    return Store(database["test_app_dsn"])


@pytest.fixture
def credentials(database):
    return {role: issue_credential(database["test_owner_dsn"], uid(role), role, duration=timedelta(hours=1))
            for role in ("owner", "research", "evaluator", "scheduler", "paper", "governance", "data", "inference", "auditor", "sealed_evaluator")}


@pytest.fixture
def isolated_restore_target(database):
    database_name = f"liki_restore_{secrets.token_hex(8)}"
    assert _RESTORE_DATABASE_NAME.fullmatch(database_name)
    created = _postgres_sql(database, f'CREATE DATABASE "{database_name}" OWNER liki_owner TEMPLATE template0;')
    assert created.returncode == 0
    database_oid = _database_oid(database, database_name)
    assert database_oid is not None
    target_dsn = make_conninfo(database["test_owner_dsn"], dbname=database_name)
    try:
        yield target_dsn
    finally:
        # Drop only the exact database this fixture created and re-identified above.
        if _database_oid(database, database_name) == database_oid:
            dropped = _postgres_sql(database, f'DROP DATABASE "{database_name}" WITH (FORCE);')
            assert dropped.returncode == 0


def _transition(store, credential, aggregate_id: str, expected_version: int):
    with store.transaction(credential) as (conn, actor):
        return store.transition(
            conn,
            actor,
            capability="research",
            kind="research_object",
            aggregate_id=aggregate_id,
            expected_version=expected_version,
            state={"restored": True, "version": expected_version + 1},
            event_type="RESTORE_TEST",
            operation_key=uid("OP"),
            task_id="restore-test",
            policy_version="test-v1",
        )


def test_backup_restore_reconstructs_exact_event_chain_and_projections(
    tmp_path: Path, database, store, credentials, isolated_restore_target
):
    aggregate_id = uid("AGG")
    _transition(store, credentials["research"], aggregate_id, 0)
    _transition(store, credentials["research"], aggregate_id, 1)
    archive = tmp_path / "liki.dump"
    key = Fernet.generate_key()

    manifest = backup_database(database["test_owner_dsn"], archive, key)
    drill = measure_restore_drill(isolated_restore_target, archive, key)
    restored = drill["restore"]

    assert restored["status"] == "RESTORED"
    assert restored["checkpoint"] == manifest["checkpoint"]
    assert restored["checkpoint"]["event_audit"]["status"] == "VERIFIED"
    assert restored["checkpoint"]["table_counts"]["event_log"] >= 2
    assert drill["recovery"]["database_restore_measurement"] == "MEASURED"
    assert drill["recovery"]["database_restore_duration_seconds"] >= 0
    assert drill["recovery"]["storage_disaster_rpo"] == "NOT_MEASURED"
    assert archive.exists() and archive.with_suffix(".dump.json").exists()


def test_restore_rejects_nonempty_target_wrong_key_and_tampering(
    tmp_path: Path, database, store, credentials, isolated_restore_target
):
    _transition(store, credentials["research"], uid("AGG"), 0)
    archive = tmp_path / "liki.dump"
    key = Fernet.generate_key()
    backup_database(database["test_owner_dsn"], archive, key)

    with pytest.raises(DomainError, match="RESTORE_TARGET_NOT_EMPTY"):
        measure_restore_drill(database["test_owner_dsn"], archive, key)
    with pytest.raises(DomainError, match="BACKUP_KEY_INVALID"):
        measure_restore_drill(isolated_restore_target, archive, Fernet.generate_key())

    tampered = tmp_path / "tampered.dump"
    tampered.write_bytes(archive.read_bytes() + b"tamper")
    tampered.with_suffix(".dump.json").write_bytes(archive.with_suffix(".dump.json").read_bytes())
    with pytest.raises(DomainError, match="BACKUP_INTEGRITY_FAILURE"):
        measure_restore_drill(isolated_restore_target, tampered, key)

    manifest = json.loads(archive.with_suffix(".dump.json").read_text())
    manifest["created_at"] = "2000-01-01T00:00:00+00:00"
    archive.with_suffix(".dump.json").write_text(json.dumps(manifest))
    with pytest.raises(DomainError, match="BACKUP_INTEGRITY_FAILURE"):
        measure_restore_drill(isolated_restore_target, archive, key)

    manifest["format_version"] = 1
    archive.with_suffix(".dump.json").write_text(json.dumps(manifest))
    with pytest.raises(DomainError, match="BACKUP_MANIFEST_INVALID"):
        measure_restore_drill(isolated_restore_target, archive, key)
