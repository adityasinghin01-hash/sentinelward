#!/usr/bin/env bash
# Copies the built web app (../../web/dist) to ./web-dist, readable by the api
# container's non-root user (uid 10001). The original build can be mode 700/600 (owner only).
# Run after every frontend build, then: docker compose up -d api
set -euo pipefail
cd "$(dirname "$0")"
src=../../web/dist
[ -f "$src/index.html" ] || { echo "no $src/index.html: build web/ first (npm run build)" >&2; exit 1; }
rm -rf web-dist.new
cp -R "$src" web-dist.new
chmod -R u=rwX,go=rX web-dist.new
rm -rf web-dist
mv web-dist.new web-dist
echo "web app copied to $(pwd)/web-dist"
