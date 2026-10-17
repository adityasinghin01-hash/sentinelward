#!/usr/bin/env bash
# Creates the container secrets once (never printed, never committed). Safe to run twice.
set -euo pipefail
cd "$(dirname "$0")"
umask 077
[ -s db_password.txt ] || python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" > db_password.txt
pw=$(cat db_password.txt)
printf 'SW_PG_DSN=postgresql://sw_api:%s@db:5432/sentinelward\nDATABASE_URL=postgresql://sw_api:%s@db:5432/sentinelward\n' "$pw" "$pw" > .env.containers
echo "secrets ready (db_password.txt, .env.containers, mode 600)"
