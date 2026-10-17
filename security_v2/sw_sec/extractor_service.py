"""Run raw receive telemetry plus a validated sw_common.Bus feature publisher."""
import os
import json
import signal
import threading
import time
from paho.mqtt import client as mqtt
from sw_common import Bus
from .features import Extractor, LogTail
from .policy import DEVICES


def main():
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *args:stop.set())
    e=Extractor()
    log=LogTail(os.environ.get('SW_MOSQUITTO_LOG','/var/log/mosquitto/mosquitto.log'),e)
    host=os.environ.get('SW_MQTT_HOST','127.0.0.1'); port=int(os.environ.get('SW_MQTT_PORT','1883'))
    user=os.environ['SW_MQTT_USERNAME']; password=os.environ['SW_MQTT_PASSWORD']
    ca=os.environ.get('SW_MQTT_CA')
    publisher=Bus(host,port,'sw-net-publisher',username=user,password=password,tls_ca_file=ca,strict=True)
    receiver=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='sw-net-receiver')
    receiver.username_pw_set(user,password)
    if ca: receiver.tls_set(ca_certs=ca)
    def on_connect(c,u,f,reason,props):
        if not reason.is_failure:
            c.subscribe([('ward/bed/+/vitals',0),('ward/demo/control',1)])
            # This partial window cannot establish a full 5 seconds of coverage.
            e.receive_coverage_start=(time.time_ns()//1_000_000//5000+1)*5000
    receiver.on_connect=on_connect
    def on_message(c,u,message):
        if message.topic=='ward/demo/control':
            try: e.control(json.loads(message.payload))
            except (ValueError,TypeError,UnicodeError): pass
        else:
            e.observe(message.topic,message.payload,time.time_ns()//1_000_000)
    receiver.on_message=on_message
    receiver.reconnect_delay_set(min_delay=1,max_delay=30)
    next_end=(time.time_ns()//1_000_000//5000+1)*5000
    e.log_coverage_start=next_end
    try:
        receiver.connect_async(host,port); receiver.loop_start(); publisher.connect(wait_s=0)
        while not stop.wait(.2):
            log.poll()
            now=time.time_ns()//1_000_000
            if now>=next_end:
                for device in DEVICES:
                    message=e.snapshot(device,next_end-5000)
                    if not receiver.is_connected() or next_end-5000<getattr(e,'receive_coverage_start',next_end):
                        for key in message:
                            if key not in ('v','type','device_id','window_start','window_s'):
                                message[key]=None
                    if publisher.is_connected: publisher.publish(message)
                # Never invent missed windows after a scheduler stall.
                next_end=(now//5000+1)*5000
    finally:
        receiver.disconnect(); receiver.loop_stop(); publisher.close()


if __name__=='__main__': main()
