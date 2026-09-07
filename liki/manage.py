import argparse
import os
from datetime import timedelta
from pathlib import Path

from liki.core import database_config
from liki.store import issue_credential, migrate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("migrate", "issue-token", "enroll-verifier"))
    parser.add_argument("--principal")
    parser.add_argument("--role")
    parser.add_argument("--output")
    parser.add_argument("--key-id")
    parser.add_argument("--public-key-file", type=Path)
    args = parser.parse_args()
    config = database_config()
    if args.action == "migrate":
        migrate(config["owner_dsn"])
        print("Database migrations applied")
    elif args.action == "enroll-verifier":
        from liki.verification import provision_verifier
        if not all((args.principal, args.key_id, args.public_key_file)):
            parser.error("enroll-verifier requires --principal, --key-id, --public-key-file")
        provision_verifier(config["owner_dsn"], principal_id=args.principal,
            key_id=args.key_id, public_key=args.public_key_file.read_bytes())
        print("Verifier public key enrolled for this code identity")
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
