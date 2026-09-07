from datetime import timedelta
import os
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from liki.core import database_config, uid
from liki.store import Store, issue_credential, migrate


class IsolatedDatabaseConfig(dict):
    def __repr__(self):
        return "<isolated test database credentials redacted>"


@pytest.fixture
def database():
    config = database_config()
    if "test_owner_dsn" not in config:
        raise RuntimeError("Integration tests require an explicitly isolated test database")
    template = conninfo_to_dict(config["test_owner_dsn"])
    if not template["dbname"].startswith("liki_test"):
        raise RuntimeError("Test database prefix must be liki_test")
    name = "liki_test_run_" + uuid4().hex
    admin_dsn = os.environ.get("LIKI_TEST_ADMIN_DATABASE_URL")

    def administrative(statement):
        if admin_dsn:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(statement)
        else:
            if template.get("host") not in {"127.0.0.1", "localhost"}:
                raise RuntimeError("Remote integration tests require a test-only admin database URL")
            subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-q", "-v", "ON_ERROR_STOP=1"],
                           input=statement.as_string(), text=True, check=True, capture_output=True)

    administrative(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(name), sql.Identifier(template["user"])))
    administrative(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC; GRANT CONNECT ON DATABASE {} TO liki_app").format(
        sql.Identifier(name), sql.Identifier(name)))
    isolated = IsolatedDatabaseConfig(config)
    for key in ("test_owner_dsn", "test_app_dsn"):
        isolated[key] = make_conninfo(config[key], dbname=name)
    try:
        migrate(isolated["test_owner_dsn"])
        yield isolated
    finally:
        # Only the exact disposable database created by this fixture is removed.
        administrative(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def store(database):
    return Store(database["test_app_dsn"])


@pytest.fixture
def credentials(database):
    return {role: issue_credential(database["test_owner_dsn"], uid(role), role,
                                   duration=timedelta(hours=1))
            for role in ("owner", "research", "evaluator", "scheduler", "paper", "governance", "data", "inference", "auditor", "sealed_evaluator")}
