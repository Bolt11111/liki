from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from cryptography.fernet import Fernet, InvalidToken
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from liki.core import DomainError
from liki.store import Store

BACKUP_FORMAT_VERSION = 2
_COMMAND_TIMEOUT_SECONDS = 300
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DURABLE_SYNCHRONOUS_COMMIT_VALUES = {"on", "local", "remote_write", "remote_apply"}


def _environment(dsn: str) -> dict[str, str]:
    info = conninfo_to_dict(dsn)
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    for field, key in (("host", "PGHOST"), ("port", "PGPORT"), ("dbname", "PGDATABASE"),
                       ("user", "PGUSER"), ("password", "PGPASSWORD"), ("sslmode", "PGSSLMODE")):
        value = info.get(field)
        if value:
            environment[key] = str(value)
    return environment


def _manifest_path(source: Path) -> Path:
    return source.with_suffix(source.suffix + ".json")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fernet(key: bytes) -> Fernet:
    try:
        return Fernet(key)
    except (TypeError, ValueError) as error:
        raise DomainError("BACKUP_KEY_INVALID") from error


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


def _manifest_mac(key: bytes, manifest: dict[str, Any]) -> str:
    try:
        key_material = base64.urlsafe_b64decode(key)
    except (TypeError, ValueError) as error:
        raise DomainError("BACKUP_KEY_INVALID") from error
    if len(key_material) != 32:
        raise DomainError("BACKUP_KEY_INVALID")
    unsigned = {name: value for name, value in manifest.items() if name != "manifest_hmac_sha256"}
    mac_key = hashlib.sha256(b"LIKI backup manifest v2\x00" + key_material).digest()
    return hmac.new(mac_key, _manifest_bytes(unsigned), hashlib.sha256).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_durable_temp(destination: Path, payload: bytes) -> tuple[Path, tuple[int, int]]:
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(16)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        stat = temporary.stat()
        return temporary, (stat.st_dev, stat.st_ino)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _publish_atomically(temporary: Path, destination: Path) -> tuple[int, int]:
    try:
        # link(2) makes publication non-overwriting even if another writer races us.
        os.link(temporary, destination)
        _fsync_directory(destination.parent)
        stat = destination.stat()
        return stat.st_dev, stat.st_ino
    finally:
        temporary.unlink(missing_ok=True)


def _public_table_counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    counts: dict[str, int] = {}
    for record in tables:
        table = record["tablename"]
        row = conn.execute(sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
            sql.Identifier("public"), sql.Identifier(table))).fetchone()
        assert row is not None
        counts[table] = row["count"]
    return counts


def _schema_migrations(conn: psycopg.Connection[Any]) -> list[dict[str, str]]:
    return [{"version": row["version"], "content_hash": row["content_hash"]}
            for row in conn.execute("SELECT version,content_hash FROM schema_migrations ORDER BY version")]


def _checkpoint(conn: psycopg.Connection[Any], dsn: str) -> dict[str, Any]:
    return {"event_audit": Store(dsn).audit(conn), "table_counts": _public_table_counts(conn),
            "schema_migrations": _schema_migrations(conn)}


def _process_crash_rpo(conn: psycopg.Connection[Any]) -> str:
    settings: dict[str, str] = {}
    for setting in ("fsync", "full_page_writes", "synchronous_commit"):
        row = conn.execute(f"SHOW {setting}").fetchone()
        assert row is not None
        settings[setting] = row[setting]
    if (settings["fsync"] == "on" and settings["full_page_writes"] == "on"
            and settings["synchronous_commit"] in _DURABLE_SYNCHRONOUS_COMMIT_VALUES):
        return "DURABLE_COMMIT"
    return "NOT_MET"


def _validate_manifest(manifest: object) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise DomainError("BACKUP_MANIFEST_INVALID")
    required = {"format_version", "created_at", "encrypted", "backup_format", "ciphertext_sha256",
                "plaintext_sha256", "bytes", "plaintext_bytes", "checkpoint", "process_crash_rpo",
                "storage_disaster_rpo", "manifest_hmac_sha256"}
    if set(manifest) != required or manifest["format_version"] != BACKUP_FORMAT_VERSION:
        raise DomainError("BACKUP_MANIFEST_INVALID")
    if manifest["encrypted"] is not True or manifest["backup_format"] != "pg_dump_custom":
        raise DomainError("BACKUP_MANIFEST_INVALID")
    if (manifest["process_crash_rpo"] not in {"DURABLE_COMMIT", "NOT_MET"}
            or manifest["storage_disaster_rpo"] != "NOT_MEASURED"):
        raise DomainError("BACKUP_MANIFEST_INVALID")
    if not isinstance(manifest["created_at"], str):
        raise DomainError("BACKUP_MANIFEST_INVALID")
    try:
        created_at = datetime.fromisoformat(manifest["created_at"])
    except ValueError as error:
        raise DomainError("BACKUP_MANIFEST_INVALID") from error
    if created_at.tzinfo is None:
        raise DomainError("BACKUP_MANIFEST_INVALID")
    for digest_name in ("ciphertext_sha256", "plaintext_sha256", "manifest_hmac_sha256"):
        digest = manifest[digest_name]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise DomainError("BACKUP_MANIFEST_INVALID")
    for size_name in ("bytes", "plaintext_bytes"):
        if not isinstance(manifest[size_name], int) or isinstance(manifest[size_name], bool) or manifest[size_name] < 1:
            raise DomainError("BACKUP_MANIFEST_INVALID")
    checkpoint = manifest["checkpoint"]
    if not isinstance(checkpoint, dict) or set(checkpoint) != {"event_audit", "table_counts", "schema_migrations"}:
        raise DomainError("BACKUP_MANIFEST_INVALID")
    event_audit = checkpoint["event_audit"]
    if not isinstance(event_audit, dict) or set(event_audit) != {"events", "head_hash", "aggregates", "status"}:
        raise DomainError("BACKUP_MANIFEST_INVALID")
    if (event_audit["status"] != "VERIFIED" or not isinstance(event_audit["events"], int)
            or isinstance(event_audit["events"], bool) or event_audit["events"] < 0
            or not isinstance(event_audit["aggregates"], int) or isinstance(event_audit["aggregates"], bool)
            or event_audit["aggregates"] < 0 or not isinstance(event_audit["head_hash"], str)
            or not isinstance(checkpoint["table_counts"], dict)
            or not isinstance(checkpoint["schema_migrations"], list)):
        raise DomainError("BACKUP_MANIFEST_INVALID")
    for table, count in checkpoint["table_counts"].items():
        if not isinstance(table, str) or not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise DomainError("BACKUP_MANIFEST_INVALID")
    for migration in checkpoint["schema_migrations"]:
        if (not isinstance(migration, dict) or set(migration) != {"version", "content_hash"}
                or not isinstance(migration["version"], str)
                or not isinstance(migration["content_hash"], str)
                or not _SHA256.fullmatch(migration["content_hash"])):
            raise DomainError("BACKUP_MANIFEST_INVALID")
    return manifest


def _empty_restore_target(dsn: str) -> None:
    try:
        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "WITH user_schemas AS (SELECT 1 FROM pg_namespace WHERE nspname NOT IN "
                "('pg_catalog','information_schema','public') AND nspname NOT LIKE 'pg_toast%' "
                "AND nspname NOT LIKE 'pg_temp_%'), public_objects AS (SELECT 1 FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' UNION ALL "
                "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' "
                "UNION ALL SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                "WHERE n.nspname='public' AND t.typtype IN ('b','c','d','e','r')) "
                "SELECT EXISTS(SELECT 1 FROM user_schemas UNION ALL SELECT 1 FROM public_objects) AS occupied"
            ).fetchone()
            assert row is not None
            if row[0]:
                raise DomainError("RESTORE_TARGET_NOT_EMPTY")
    except psycopg.Error as error:
        raise DomainError("RESTORE_TARGET_UNAVAILABLE") from error


def backup_database(dsn: str, destination: Path, key: bytes) -> dict[str, Any]:
    destination = destination.resolve()
    manifest_path = _manifest_path(destination)
    if destination.exists() or manifest_path.exists():
        raise DomainError("BACKUP_ALREADY_EXISTS")
    cipher = _fernet(key)
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _fsync_directory(destination.parent)
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                snapshot = conn.execute("SELECT pg_export_snapshot() AS snapshot").fetchone()
                assert snapshot is not None
                checkpoint = _checkpoint(conn, dsn)
                process_crash_rpo = _process_crash_rpo(conn)
                result = subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--no-password", "--snapshot", snapshot["snapshot"]], env=_environment(dsn), capture_output=True, timeout=_COMMAND_TIMEOUT_SECONDS)
    except (OSError, psycopg.Error, subprocess.TimeoutExpired) as error:
        raise DomainError("BACKUP_FAILED") from error
    if result.returncode:
        raise DomainError("BACKUP_FAILED")
    try:
        ciphertext = cipher.encrypt(result.stdout)
    except (TypeError, ValueError) as error:
        raise DomainError("BACKUP_KEY_INVALID") from error
    manifest: dict[str, Any] = {"format_version": BACKUP_FORMAT_VERSION, "created_at": datetime.now(UTC).isoformat(),
                                "encrypted": True, "backup_format": "pg_dump_custom", "ciphertext_sha256": _sha256(ciphertext),
                                "plaintext_sha256": _sha256(result.stdout), "bytes": len(ciphertext), "plaintext_bytes": len(result.stdout),
                                "checkpoint": checkpoint, "process_crash_rpo": process_crash_rpo,
                                "storage_disaster_rpo": "NOT_MEASURED"}
    manifest["manifest_hmac_sha256"] = _manifest_mac(key, manifest)
    ciphertext_temp, _ = _write_durable_temp(destination, ciphertext)
    try:
        _publish_atomically(ciphertext_temp, destination)
        manifest_temp, _ = _write_durable_temp(manifest_path, _manifest_bytes(manifest))
        _publish_atomically(manifest_temp, manifest_path)
    except (FileExistsError, OSError) as error:
        raise DomainError("BACKUP_ALREADY_EXISTS") from error
    return manifest


def restore_database(dsn: str, source: Path, key: bytes) -> dict[str, Any]:
    source = source.resolve()
    manifest_path = _manifest_path(source)
    _empty_restore_target(dsn)
    try:
        manifest = _validate_manifest(json.loads(manifest_path.read_text()))
        encrypted = source.read_bytes()
    except (OSError, json.JSONDecodeError) as error:
        raise DomainError("BACKUP_MANIFEST_INVALID") from error
    if len(encrypted) != manifest["bytes"] or not hmac.compare_digest(_sha256(encrypted), manifest["ciphertext_sha256"]):
        raise DomainError("BACKUP_INTEGRITY_FAILURE")
    cipher = _fernet(key)
    try:
        plain = cipher.decrypt(encrypted)
    except InvalidToken as error:
        raise DomainError("BACKUP_KEY_INVALID") from error
    if len(plain) != manifest["plaintext_bytes"] or not hmac.compare_digest(_sha256(plain), manifest["plaintext_sha256"]):
        raise DomainError("BACKUP_INTEGRITY_FAILURE")
    if not hmac.compare_digest(_manifest_mac(key, manifest), manifest["manifest_hmac_sha256"]):
        raise DomainError("BACKUP_INTEGRITY_FAILURE")
    database_name = conninfo_to_dict(dsn).get("dbname")
    if not database_name:
        raise DomainError("RESTORE_DATABASE_NOT_CONFIGURED")
    try:
        result = subprocess.run(["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", "--no-password", "--dbname", str(database_name)], input=plain, env=_environment(dsn), capture_output=True, timeout=_COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise DomainError("RESTORE_FAILED") from error
    if result.returncode:
        raise DomainError("RESTORE_FAILED")
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            restored_checkpoint = _checkpoint(conn, dsn)
    except (psycopg.Error, DomainError) as error:
        raise DomainError("RESTORE_AUDIT_FAILURE") from error
    if restored_checkpoint != manifest["checkpoint"]:
        raise DomainError("RESTORE_AUDIT_FAILURE")
    return {"status": "RESTORED", "checkpoint": restored_checkpoint,
            "source_plaintext_sha256": manifest["plaintext_sha256"]}
