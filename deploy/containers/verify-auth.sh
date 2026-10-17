#!/usr/bin/env bash
# Against this Compose hub only. Publishes non-retained, schema-invalid probe JSON.
# Run between demos; see README. Credentials stay in root-only client config files.
set -euo pipefail
cd "$(dirname "$0")"

docker compose exec -T --user 0:0 hub /bin/sh -s <<'SH'
set -eu
export LC_ALL=C
command -v timeout >/dev/null
probe_dir=$(mktemp -d /run/mosquitto/auth-check.XXXXXX)
trap 'rm -rf "$probe_dir"' EXIT HUP INT TERM
passed=0

fail() {
    # Do not dump client output/config: keep evidence free of credentials.
    printf 'FAIL %s\n' "$*" >&2
    exit 1
}

pass() {
    passed=$((passed + 1))
    printf 'PASS %s\n' "$*"
}

# An empty config directory overrides the hub's authenticated healthcheck defaults.
# A timeout, TCP failure, or unexpected refusal is a failure, never rejection evidence.
rc=0
output=$(XDG_CONFIG_HOME="$probe_dir" timeout 6 mosquitto_sub \
    -h 127.0.0.1 -p 1883 -V mqttv5 -t ward/demo/control -E -W 3 -d 2>&1) || rc=$?
[ "$rc" -eq 135 ] || fail "anonymous: expected CONNACK 135, exit=$rc"
printf '%s\n' "$output" | grep -Fq 'received CONNACK (135)' || fail 'anonymous: missing CONNACK 135'
pass 'anonymous connect refused (CONNACK 135)'

for service in sim brain api attacks; do
    # Authenticate every role independently before interpreting denied publishes.
    rc=0
    output=$(XDG_CONFIG_HOME="/run/mqtt-clients/$service" timeout 6 mosquitto_sub \
        -h 127.0.0.1 -p 1883 -V mqttv5 -t ward/demo/control -q 1 -E -W 3 -d 2>&1) || rc=$?
    [ "$rc" -eq 0 ] || fail "$service: authenticated subscribe exit=$rc"
    printf '%s\n' "$output" | grep -Fq 'received CONNACK (0)' || fail "$service: missing successful CONNACK"
    printf '%s\n' "$output" | grep -Fq 'Subscribed (mid: 1): 1' || fail "$service: missing successful SUBACK"
    pass "$service authenticated control subscription"
done

check_publish() {
    service=$1 expected=$2 topic=$3
    rc=0
    output=$(XDG_CONFIG_HOME="/run/mqtt-clients/$service" timeout 6 mosquitto_pub \
        -h 127.0.0.1 -p 1883 -V mqttv5 -q 1 -d -t "$topic" \
        -m '{"compose_auth_probe":true}' 2>&1) || rc=$?
    # Mosquitto 2.0.22 can exit 0 even for a rejected QoS 1 publish. Inspect PUBACK.
    # https://github.com/eclipse-mosquitto/mosquitto/blob/v2.0.22/client/pub_client.c
    case "$rc" in 0|135) ;; *) fail "$service $topic: unexpected exit=$rc" ;; esac
    printf '%s\n' "$output" | grep -Fq 'received CONNACK (0)' || fail "$service $topic: authentication failed"
    ack=$(printf '%s\n' "$output" | sed -n 's/.*received PUBACK (Mid: 1, RC:\([0-9][0-9]*\)).*/\1/p')
    case "$expected:$ack:$rc" in
        allow:0:0|allow:16:0) pass "$service publish allowed $topic (PUBACK $ack)" ;;
        deny:135:*) pass "$service publish denied $topic (PUBACK 135)" ;;
        *) fail "$service $topic: expected=$expected PUBACK=${ack:-missing} exit=$rc" ;;
    esac
}

# Expectations are independent of mosquitto.acl, so accidentally broadening an ACL
# fails this matrix. Cover every write class, all 12 attack beds, scale beds and
# representative forbidden/extra-level topics. This is not an exhaustive proof.
topics='ward/bed/B01/score/M1 ward/bed/B96/score/M6
ward/bed/B01/verdict ward/bed/B96/verdict
ward/bed/B01/bedside ward/bed/B96/bedside
ward/request ward/demo/control ward/action ward/alert ward/record
net/device/MON-01/features ward/chip/B01
$CONTROL/dynamic-security/v1 $SYS/broker/uptime unrelated/probe
ward/bed/B01/vitals/extra ward/bed/B01/score/M1/extra ward/bed/B01/bedside/extra'
for bed in 01 02 03 04 05 06 07 08 09 10 11 12 13 96; do
    topics="$topics ward/bed/B$bed/vitals"
done
for service in sim brain api attacks; do
    for topic in $topics; do
        expected=deny
        case "$service:$topic" in
            sim:ward/bed/B[0-9][0-9]/vitals | \
            brain:ward/bed/B[0-9][0-9]/score/M[1-6] | \
            brain:ward/bed/B[0-9][0-9]/verdict | \
            api:ward/request | api:ward/demo/control | api:ward/action | \
            api:ward/bed/B[0-9][0-9]/bedside | \
            attacks:ward/bed/B0[1-9]/vitals | attacks:ward/bed/B1[0-2]/vitals)
                expected=allow ;;
        esac
        check_publish "$service" "$expected" "$topic"
    done
done
printf 'PASS %s checks; MQTT v5 broker acknowledgements verified\n' "$passed"
SH
