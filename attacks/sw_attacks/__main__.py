"""Run one bounded attack publisher, controlled by ward/demo/control."""
import argparse
import logging
import os
import time


def main():
    parser=argparse.ArgumentParser(description='SentinelWard finite doc-12 attack schedule')
    parser.add_argument('--fixtures',help='Original full-frame JSONL prehistory for seeks')
    parser.add_argument('--runs-dir',default=os.environ.get('SW_RUNS'),help='Attack event-log parent directory')
    parser.add_argument('--schedule',help='Explicit schedule.yaml path')
    parser.add_argument('--check-schedule',action='store_true',help='Validate and print the finite schedule, then exit')
    options=parser.parse_args()
    from .schedule import load_schedule
    if options.check_schedule:
        import json
        print(json.dumps(load_schedule(options.schedule),indent=2)); return
    logging.basicConfig(level=os.environ.get('SW_LOG_LEVEL','INFO'))
    # Only the shared io seam constructs MQTT connections. Attack-specific values
    # override this process's environment without changing the monitor publisher.
    for suffix in ('HOST','PORT','USERNAME','PASSWORD','TLS','CA'):
        value=os.environ.get('SW_ATTACK_MQTT_'+suffix)
        if value is not None: os.environ['SW_MQTT_'+suffix]=value
    from sw_brain.io import MQTTBus
    from .service import AttackService
    bus=MQTTBus(client_id=os.environ.get('SW_ATTACK_CLIENT_ID','sw-attacks'))
    service=AttackService(bus,runs_dir=options.runs_dir,schedule_path=options.schedule,fixtures=options.fixtures)
    bus.connect()
    try:
        while True:
            bus.drain(); service.tick(int(time.time()*1000)); time.sleep(.01)
    except KeyboardInterrupt: pass
    finally: service.close(int(time.time()*1000)); bus.close()

if __name__=='__main__': main()
