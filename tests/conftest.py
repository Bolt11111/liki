from datetime import timedelta

import pytest

from liki.core import database_config, uid
from liki.store import Store, issue_credential, migrate


@pytest.fixture(scope="session")
def database():
    config = database_config()
    if "test_owner_dsn" not in config:
        raise RuntimeError("Integration tests require an explicitly isolated test database")
    migrate(config["test_owner_dsn"])
    return config


@pytest.fixture
def store(database):
    return Store(database["test_app_dsn"])


@pytest.fixture
def credentials(database):
    return {role: issue_credential(database["test_owner_dsn"], uid(role), role,
                                   duration=timedelta(hours=1))
            for role in ("owner", "research", "evaluator", "scheduler", "paper", "governance", "data", "inference", "auditor", "sealed_evaluator")}
