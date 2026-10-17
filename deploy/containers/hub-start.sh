#!/bin/sh
# Root startup only: copy the 0600 host secret without chowning the bind mount.
# Mosquitto drops to its own user before accepting connections.
set -eu
umask 077
cp /run/secrets/mqtt_passwords /run/mosquitto/passwords
chown mosquitto:mosquitto /run/mosquitto/passwords /mosquitto/data
chmod 600 /run/mosquitto/passwords
exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
