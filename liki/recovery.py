"""Measured recovery evidence without unsupported disaster-recovery claims."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from liki.backup import restore_database
from liki.core import DomainError, content_hash, utcnow

_DURABLE_SYNCHRONOUS_COMMIT_VALUES = {"on", "local", "remote_write", "remote_apply"}


def durability_settings_fingerprint(dsn: str) -> dict[str, Any]:
    setting_names = ("fsync", "full_page_writes", "synchronous_commit", "wal_level", "archive_mode")
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            settings = {}
            for setting in setting_names:
                row = conn.execute(f"SHOW {setting}").fetchone()
                assert row is not None
                settings[setting] = row[setting]
            try:
                replica_row = conn.execute("SELECT count(*) AS count FROM pg_stat_replication WHERE sync_state='sync'").fetchone()
                synchronous_replicas = replica_row["count"] if replica_row is not None else 0
            except psycopg.Error:
                synchronous_replicas = "NOT_MEASURED"
    except psycopg.Error as error:
        raise DomainError("DURABILITY_SETTINGS_UNAVAILABLE") from error
    evidence = {"settings": settings, "synchronous_replicas": synchronous_replicas}
    return {**evidence, "fingerprint": content_hash(evidence)}


def recovery_report(dsn: str, *, database_restore_duration_seconds: float | None = None) -> dict[str, Any]:
    if (database_restore_duration_seconds is not None
            and (isinstance(database_restore_duration_seconds, bool)
                 or not math.isfinite(database_restore_duration_seconds)
                 or database_restore_duration_seconds < 0)):
        raise DomainError("INVALID_RESTORE_DURATION")
    durability = durability_settings_fingerprint(dsn)
    settings = durability["settings"]
    process_crash_rpo = "DURABLE_COMMIT" if settings["fsync"] == "on" and settings["full_page_writes"] == "on" and settings["synchronous_commit"] in _DURABLE_SYNCHRONOUS_COMMIT_VALUES else "NOT_MET"
    measured = database_restore_duration_seconds is not None
    return {"recorded_at_utc": utcnow(), "durability": durability, "process_crash_rpo": process_crash_rpo,
            "storage_disaster_rpo": "NOT_MEASURED", "database_restore_duration_seconds": database_restore_duration_seconds,
            "database_restore_measurement": "MEASURED" if measured else "NOT_MEASURED",
            "control_plane_rto_target_seconds": 300, "control_plane_rto_measurement": "NOT_MEASURED",
            "full_service_rto_target_seconds": 1800, "full_service_rto_measurement": "NOT_MEASURED"}


def measure_restore_drill(dsn: str, source: Path, key: bytes) -> dict[str, Any]:
    started_at = time.monotonic()
    restored = restore_database(dsn, source, key)
    duration = time.monotonic() - started_at
    return {"restore": restored, "recovery": recovery_report(dsn, database_restore_duration_seconds=duration)}
