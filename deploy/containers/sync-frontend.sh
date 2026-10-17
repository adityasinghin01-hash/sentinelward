#!/usr/bin/env bash
# Copies the built web app (../../frontend/dist) to ./frontend-dist, readable by the api
# container's non-root user (uid 10001). The original build can be mode 700/600 (owner only).
# Run after every frontend build, then: docker compose up -d api
set -euo pipefail
cd "$(dirname "$0")"
src=../../frontend/dist
[ -f "$src/index.html" ] || { echo "no $src/index.html: build the frontend first" >&2; exit 1; }
rm -rf frontend-dist.new
cp -R "$src" frontend-dist.new
chmod -R u=rwX,go=rX frontend-dist.new
rm -rf frontend-dist
mv frontend-dist.new frontend-dist
echo "frontend copied to $(pwd)/frontend-dist"
