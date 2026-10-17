#!/usr/bin/env bash
# Judges' evidence for criterion 3 (containers, security, scalability, compute) on LinuxONE.
# Writes plain-text captures to ../evidence/containers/ (or $SW_EVIDENCE_OUT) for screenshots. Prints no secrets.
set -euo pipefail
cd "$(dirname "$0")"
out=${SW_EVIDENCE_OUT:-../evidence/containers}
mkdir -p "$out"
{
  echo "# $(date -u +%FT%TZ)  $(uname -m)  $(grep -m1 'Type:' /proc/sysinfo 2>/dev/null || true)"
  docker version --format 'docker {{.Server.Version}} on {{.Server.Os}}/{{.Server.Arch}}'
} > "$out/platform.txt"
docker compose ps > "$out/compose-ps.txt"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}' > "$out/stats.txt"
for s in api brain sim attacks; do
  docker inspect "sentinelward-$s-1" --format "$s: user={{.Config.User}} readonly={{.HostConfig.ReadonlyRootfs}} caps_dropped={{.HostConfig.CapDrop}} security_opt={{.HostConfig.SecurityOpt}} mem={{.HostConfig.Memory}} nanocpus={{.HostConfig.NanoCpus}}"
done > "$out/hardening.txt"
docker image inspect sentinelward:latest --format 'image arch={{.Architecture}} os={{.Os}} size={{.Size}}' > "$out/image.txt"
curl -s 127.0.0.1:8001/api/health > "$out/health.json" || true
echo "evidence written to $out"
