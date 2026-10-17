#!/usr/bin/env bash
# Start IBM Granite on this LinuxONE server for the agents' shift briefing (A8).
# Uses IBM's LinuxONE Community Cloud lab image (llama-cpp-python + big-endian Granite GGUF inside).
# Listens on 127.0.0.1:8090 only. Then set SW_GRANITE_URL=http://127.0.0.1:8090 for the agents.
set -euo pipefail
IMAGE=registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${GRANITE_PORT:-8090}"

docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull "$IMAGE"

# Find the Granite model file inside the image (path is not documented by IBM).
MODEL="$(docker run --rm --entrypoint /bin/sh "$IMAGE" -c "find / -xdev -name 'granite*.gguf' 2>/dev/null | head -1")"
[ -n "$MODEL" ] || { echo "no granite*.gguf found in $IMAGE" >&2; exit 1; }
echo "model inside image: $MODEL"

docker rm -f granite >/dev/null 2>&1 || true
docker run -d --name granite --restart unless-stopped \
  --network host \
  --memory 2g --cpus 1.0 \
  --security-opt no-new-privileges:true --cap-drop ALL \
  -v "$HERE/granite_server.py:/srv/granite_server.py:ro" \
  --entrypoint /opt/venv/bin/python \
  "$IMAGE" /srv/granite_server.py --model "$MODEL" --port "$PORT" --threads 1

for i in $(seq 1 60); do
  if curl -fs "127.0.0.1:$PORT/health" >/dev/null; then
    curl -s "127.0.0.1:$PORT/health"; echo
    exit 0
  fi
  sleep 2
done
echo "Granite did not become healthy; see: docker logs granite" >&2
exit 1
