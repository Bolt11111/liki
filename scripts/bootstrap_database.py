"""Provision isolated development roles without logging credentials."""

import json
import os
import secrets
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql

target = Path(".runtime/database.json")
target.parent.mkdir(mode=0o700, exist_ok=True)
if target.exists():
    # Existing credentials must remain stable across setup/restarts.
    config = json.loads(target.read_text())
    with psycopg.connect(config["owner_dsn"]):
        pass
else:
    owner_password = secrets.token_urlsafe(40)
    app_password = secrets.token_urlsafe(40)
    commands = []
    for role, password in (("liki_owner", owner_password), ("liki_app", app_password)):
        commands.append(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {};").format(sql.Identifier(role), sql.Literal(password)).as_string())
    for database in ("liki_dev", "liki_test"):
        commands.extend([f"CREATE DATABASE {database} OWNER liki_owner;",
                         f"REVOKE ALL ON DATABASE {database} FROM PUBLIC;",
                         f"GRANT CONNECT ON DATABASE {database} TO liki_app;"])
    subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-v", "ON_ERROR_STOP=1", "-q"],
                   input="\n".join(commands), text=True, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE)
    payload = {"owner_dsn": f"postgresql://liki_owner:{owner_password}@127.0.0.1/liki_dev",
               "app_dsn": f"postgresql://liki_app:{app_password}@127.0.0.1/liki_dev",
               "test_owner_dsn": f"postgresql://liki_owner:{owner_password}@127.0.0.1/liki_test",
               "test_app_dsn": f"postgresql://liki_app:{app_password}@127.0.0.1/liki_test"}
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream)
