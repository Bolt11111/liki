import argparse
import os
from datetime import timedelta
from pathlib import Path

from liki.core import database_config
from liki.store import issue_credential, migrate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("migrate", "issue-token"))
    parser.add_argument("--principal")
    parser.add_argument("--role")
    parser.add_argument("--output")
    args = parser.parse_args()
    config = database_config()
    if args.action == "migrate":
        migrate(config["owner_dsn"])
        print("Database migrations applied")
    else:
        if not all((args.principal, args.role, args.output)):
            parser.error("issue-token requires --principal, --role, --output")
        token = issue_credential(config["owner_dsn"], args.principal, args.role, duration=timedelta(hours=24))
        path = Path(args.output)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(token.token)
        print("Scoped credential written to protected file; expires in 24 hours")


if __name__ == "__main__":
    main()
