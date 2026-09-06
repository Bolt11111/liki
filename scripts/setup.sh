#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v psql >/dev/null || ! command -v bwrap >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-client bubblewrap
fi
uv sync --frozen
cluster="$(pg_lsclusters --no-header | awk 'NR==1 {print $1 " " $2}')"
read -r pg_version pg_cluster <<< "$cluster"
pg_ctlcluster "$pg_version" "$pg_cluster" start || pg_isready -q
mkdir -p .runtime
chmod 700 .runtime
uv run python scripts/bootstrap_database.py
uv run python -m liki.manage migrate
uv run python tools/requirements.py check
