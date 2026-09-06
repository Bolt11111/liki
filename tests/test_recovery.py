from __future__ import annotations

import math
import re
import secrets

import pytest
from psycopg.conninfo import make_conninfo

from liki.core import DomainError
from liki.recovery import recovery_report
from tests.test_backup import _database_oid, _postgres_sql

_RECOVERY_DATABASE_NAME = re.compile(r"liki_recovery_[0-9a-f]{16}")


@pytest.fixture(scope="module")
def database():
    from liki.core import database_config

    runtime = database_config()
    database_name = f"liki_recovery_{secrets.token_hex(8)}"
    assert _RECOVERY_DATABASE_NAME.fullmatch(database_name)
    control = {"test_owner_dsn": runtime["test_owner_dsn"]}
    created = _postgres_sql(control, f'CREATE DATABASE "{database_name}" OWNER liki_owner TEMPLATE template0;')
    assert created.returncode == 0
    database_oid = _database_oid(control, database_name)
    assert database_oid is not None
    try:
        yield {"test_owner_dsn": make_conninfo(runtime["test_owner_dsn"], dbname=database_name)}
    finally:
        if _database_oid(control, database_name) == database_oid:
            dropped = _postgres_sql(control, f'DROP DATABASE "{database_name}" WITH (FORCE);')
            assert dropped.returncode == 0


def test_recovery_report_distinguishes_process_and_storage_rpo(database):
    report = recovery_report(database["test_owner_dsn"])

    assert report["process_crash_rpo"] in {"DURABLE_COMMIT", "NOT_MET"}
    assert report["storage_disaster_rpo"] == "NOT_MEASURED"
    assert report["database_restore_measurement"] == "NOT_MEASURED"
    assert report["control_plane_rto_measurement"] == "NOT_MEASURED"
    assert report["full_service_rto_measurement"] == "NOT_MEASURED"
    assert report["durability"]["fingerprint"].startswith("sha256:")


@pytest.mark.parametrize("duration", [-0.1, math.inf, math.nan, False])
def test_recovery_report_rejects_invalid_measurements(database, duration):
    with pytest.raises(DomainError, match="INVALID_RESTORE_DURATION"):
        recovery_report(database["test_owner_dsn"], database_restore_duration_seconds=duration)
