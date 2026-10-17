#!/usr/bin/env python3
"""Bridge the shared server MQTT env to the brain seam without exposing secrets."""
import os
import sys


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: service_env.py command [arguments...]')
    for destination, source in [('SW_MQTT_HOST', 'MQTT_HOST'), ('SW_MQTT_PORT', 'MQTT_PORT'),
                                ('SW_MQTT_USERNAME', 'MQTT_USER'), ('SW_MQTT_PASSWORD', 'MQTT_PASS')]:
        if source in os.environ:
            os.environ.setdefault(destination, os.environ[source])
    if sys.argv[2:] == ['-m', 'sw_api']:
        # Server .env provides DATABASE_URL; the backend reads SW_PG_DSN (default "memory").
        if os.environ.get('DATABASE_URL') and not os.environ.get('SW_PG_DSN', '').strip():
            os.environ['SW_PG_DSN'] = os.environ['DATABASE_URL']
        os.environ['SW_API_HOST'] = '127.0.0.1'
        os.environ['SW_API_PORT'] = '8000'
        os.environ['SW_FRONTEND_DIST'] = '/home/linux1/sw/app/web/dist'
    os.execv(sys.argv[1], sys.argv[1:])


if __name__ == '__main__':
    main()
