"""Bounded MQTT v5 probes: explicit broker reason codes, never timeout-as-denial."""
import threading
import time
from paho.mqtt import client as mqtt


def probe(host, port, *, username=None, password=None, client_id='', ca=None, topic=None, subscribe=False, payload=b'{}'):
    result={'connect':None,'publish':None,'subscribe':None}
    connected=threading.Event(); completed=threading.Event()
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=client_id,protocol=mqtt.MQTTv5)
    if username is not None: client.username_pw_set(username,password)
    if ca: client.tls_set(ca_certs=str(ca))
    def on_connect(c,u,f,reason,props):
        result['connect']=reason.value
        connected.set()
    def on_publish(c,u,mid,reason,props):
        result['publish']=reason.value
        completed.set()
    def on_subscribe(c,u,mid,reasons,props):
        result['subscribe']=[r.value for r in reasons]
        completed.set()
    client.on_connect=on_connect; client.on_publish=on_publish; client.on_subscribe=on_subscribe
    client.reconnect_delay_set(min_delay=30,max_delay=30)
    try:
        client.connect(host,port,keepalive=10)
        client.loop_start()
        if not connected.wait(5): raise TimeoutError('No broker CONNACK')
        if result['connect']==0 and topic:
            if subscribe: client.subscribe(topic,qos=1)
            else: client.publish(topic,payload,qos=1)
            if not completed.wait(5): raise TimeoutError('No broker PUBACK/SUBACK')
        return result
    finally:
        client.disconnect(); client.loop_stop()


def clean_session(host,port,device,password):
    # MQTT 3.1.1 CleanSession=1 explicitly removes the previous saved session.
    event=threading.Event(); accepted=[]
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=device,clean_session=True)
    client.username_pw_set(device,password)
    def on_connect(c,u,f,reason,props):
        accepted.append(not reason.is_failure); event.set()
    client.on_connect=on_connect
    try:
        client.connect(host,port,keepalive=10); client.loop_start()
        if not event.wait(5) or accepted!=[True]: raise RuntimeError('Clean-session connection not accepted')
    finally:
        client.disconnect(); client.loop_stop()
