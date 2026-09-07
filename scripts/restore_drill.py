"""Restore one encrypted archive into a dedicated, empty drill database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from liki.recovery import measure_restore_drill


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--target-dsn-env", default="LIKI_RESTORE_TARGET_DSN")
    args = parser.parse_args()
    target_dsn = os.environ.get(args.target_dsn_env)
    if not target_dsn:
        parser.error(f"{args.target_dsn_env} must contain the dedicated empty restore-target DSN")
    try:
        key = args.key_file.read_bytes().strip()
    except OSError as error:
        parser.error(f"cannot read key file: {error.__class__.__name__}")
    print(json.dumps(measure_restore_drill(target_dsn, args.source, key), sort_keys=True, default=str))


if __name__ == "__main__":
    main()
