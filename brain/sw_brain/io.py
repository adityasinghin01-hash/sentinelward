"""Locked doc-00 transport boundary. No model imports MQTT directly."""
from __future__ import annotations
from dataclasses import dataclass
import json
import math
import os
import queue
import re
import time
import threading
from typing import Protocol

BEDS = {f'B{i:02d}' for i in range(1,13)}
DEVICES = {f'MON-{i:02d}' for i in range(1,13)}
MODELS = {f'M{i}' for i in range(1,7)}
ALARMS = {'ASYSTOLE','BRADY','TACHY','VTACH','VFIB'}
PRIORITIES = {'NORMAL':'none','EMERGENCY':'high','BOTH':'high','TAMPERING':'medium','UNSURE':'medium','DRIFTING':'medium','LOOSE_SENSOR':'low','DEVICE_ATTACK':'none'}

@dataclass(frozen=True)
class Receipt:
    topic: str
    data: dict
    received_ms: int
    payload_bytes: int
    sender_id: str | None = None  # Only broker-authenticated metadata, never payload identity.
    received_mono_ms: int | None = None

class Bus(Protocol):
    def subscribe(self, topic: str, callback, qos: int = 1): ...
    def publish(self, topic: str, data: dict, qos: int = 1, retain: bool = False): ...


def number(value, nullable=False, integer=False, minimum=None):
    if value is None and nullable: return
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError('Expected finite number')
    if integer and type(value) is not int: raise ValueError('Expected integer')
    if minimum is not None and value<minimum: raise ValueError('Number below minimum')


def require(data, fields):
    if not set(fields).issubset(data): raise ValueError('Missing fields: '+str(set(fields)-data.keys()))


def samples(value):
    if value is None: return
    if not isinstance(value,list) or len(value)!=125: raise ValueError('Expected 125 samples or null')
    for item in value: number(item,nullable=True)


def validate(topic,data):
    if not isinstance(data,dict) or type(data.get('v')) is not int or data['v']!=1: raise ValueError('Expected v1 object')
    kind=data.get('type')
    if kind=='vitals':
        require(data,('bed_id','device_id','seq','ts','fs','ecg','ppg','abp','hr','spo2','rr','nibp','monitor_alarm'))
        if data['bed_id'] not in BEDS or data['device_id'] not in DEVICES or data['device_id'][4:]!=data['bed_id'][1:]: raise ValueError('Bed/device mismatch')
        expected=f"ward/bed/{data['bed_id']}/vitals"
        number(data['seq'],integer=True,minimum=0); number(data['ts'],integer=True,minimum=0)
        if data['ts']%1000 or type(data['fs']) is not int or data['fs']!=125: raise ValueError('Expected second aligned 125 Hz chunk')
        for name in ('ecg','ppg','abp'): samples(data[name])
        for name in ('hr','spo2','rr'): number(data[name],nullable=True)
        if data['nibp'] is not None:
            if not isinstance(data['nibp'],dict): raise ValueError('Invalid cuff')
            require(data['nibp'],('sys','dia','map','ts'))
            for key in ('sys','dia','map'): number(data['nibp'][key],nullable=True)
            number(data['nibp']['ts'],integer=True,minimum=0)
        if data['monitor_alarm'] is not None:
            alarm=data['monitor_alarm']
            if not isinstance(alarm,dict) or set(alarm)!={'code','priority'} or alarm['code'] not in ALARMS or alarm['priority'] not in {'high','medium','low'}: raise ValueError('Invalid monitor alarm')
    elif kind=='score':
        require(data,('bed_id','model','model_version','window_start','window_s','score','label','reason','extra'))
        if data['bed_id'] not in BEDS or data['model'] not in MODELS: raise ValueError('Invalid score identifiers')
        expected=f"ward/bed/{data['bed_id']}/score/{data['model']}"
        number(data['score'],nullable=True)
        if data['score'] is not None and not 0<=data['score']<=1: raise ValueError('Score out of range')
        if not isinstance(data['reason'],str) or len(data['reason'])>120 or not isinstance(data['extra'],dict): raise ValueError('Invalid score explanation')
        if not isinstance(data['model_version'],str) or not isinstance(data['label'],str): raise ValueError('Invalid score label')
    elif kind=='verdict':
        require(data,('bed_id','ts','window_start','verdict','priority','confidence','trust','last_trusted_ts','reasons','scores'))
        if data['bed_id'] not in BEDS or data['verdict'] not in PRIORITIES or data['priority']!=PRIORITIES[data['verdict']]: raise ValueError('Invalid verdict')
        expected=f"ward/bed/{data['bed_id']}/verdict"
        number(data['ts'],integer=True,minimum=0); number(data['last_trusted_ts'],nullable=True,integer=True,minimum=0)
        for key in ('confidence','trust'):
            number(data[key])
            if not 0<=data[key]<=1: raise ValueError('Invalid probability')
        if not isinstance(data['reasons'],list) or len(data['reasons'])>3 or any(not isinstance(s,str) or len(s)>120 for s in data['reasons']): raise ValueError('Invalid reasons')
        if set(data['scores'])!=MODELS: raise ValueError('Six scores required')
        for value in data['scores'].values():
            number(value,nullable=True)
            if value is not None and not 0<=value<=1: raise ValueError('Invalid score')
    elif kind=='net_features':
        require(data,('device_id','window_start','window_s','msgs_per_s','bytes_per_s','iat_mean_ms','iat_std_ms','payload_mean','payload_std','senders','connects_per_s','malformed','seq_gaps','seq_repeats','stale_ms'))
        if data['device_id'] not in DEVICES: raise ValueError('Invalid device')
        expected=f"net/device/{data['device_id']}/features"
        for key in ('msgs_per_s','bytes_per_s','iat_mean_ms','iat_std_ms','payload_mean','payload_std','senders','connects_per_s','malformed','seq_gaps','seq_repeats','stale_ms'): number(data[key],nullable=True,minimum=0)
        if data['window_s']!=5: raise ValueError('Expected 5-second network window')
    elif kind=='bedside_check':
        require(data,('bed_id','ts','result','by'))
        if data['bed_id'] not in BEDS or data['result'] not in {'patient_ok','patient_not_ok'} or not isinstance(data['by'],str) or not data['by'].startswith('staff:'): raise ValueError('Invalid bedside check')
        number(data['ts'],integer=True,minimum=0)
        expected=f"ward/bed/{data['bed_id']}/bedside"
    elif kind=='demo_control':
        require(data,('ts','cmd','run_id','start_at_s'))
        if data['cmd'] not in {'run','reset'} or not isinstance(data['run_id'],str) or re.fullmatch(r'[A-Za-z0-9_-]{1,80}',data['run_id']) is None: raise ValueError('Invalid control')
        number(data['ts'],integer=True,minimum=0); number(data['start_at_s'],minimum=0)
        if data['start_at_s']>1200: raise ValueError('Seek beyond script')
        expected='ward/demo/control'
    else: raise ValueError('Unsupported message type')
    if kind in {'score','verdict','net_features'}:
        number(data['window_start'],integer=True,minimum=0)
        if data['window_start']%5000: raise ValueError('Window not aligned')
    if kind=='score' and data['window_s']!=10: raise ValueError('Expected 10-second scores')
    if topic!=expected: raise ValueError('Topic/payload mismatch')
    return data


def decode(topic,payload,received_ms=None,sender_id=None,received_mono_ms=None):
    raw=payload.encode() if isinstance(payload,str) else payload
    if not isinstance(raw,bytes) or len(raw)>262144: raise ValueError('Invalid payload size')
    try:
        data=json.loads(raw,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
        validate(topic,data)
    except (UnicodeDecodeError,json.JSONDecodeError,TypeError,OverflowError,KeyError,RecursionError) as exc:
        raise ValueError('Invalid JSON message') from exc
    return Receipt(topic,data,int(time.time()*1000) if received_ms is None else received_ms,len(raw),sender_id,received_mono_ms)


def encode(topic,data):
    validate(topic,data)
    return json.dumps(data,separators=(',',':'),allow_nan=False).encode()

class MemoryBus:
    def __init__(self): self.published=[]; self.subscriptions=[]
    def subscribe(self,topic,callback,qos=1): self.subscriptions.append((topic,callback,qos))
    def publish(self,topic,data,qos=1,retain=False):
        encode(topic,data)
        self.published.append((topic,data,qos,retain))

class MQTTBus:
    """Network callbacks enqueue bounded receipts; one main thread runs inference."""
    def __init__(self,client_id='sw-brain',max_queue=4096):
        import paho.mqtt.client as mqtt
        self.client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=client_id)
        self.callbacks=[]; self.queue=queue.Queue(maxsize=max_queue); self.dropped=0
        self.safety_pending={}  # bounded latest safety message per topic
        self.safety_lock=threading.Lock()
        username=os.environ.get('SW_MQTT_USERNAME'); password=os.environ.get('SW_MQTT_PASSWORD')
        if username: self.client.username_pw_set(username,password)
        if os.environ.get('SW_MQTT_TLS')=='1': self.client.tls_set(ca_certs=os.environ.get('SW_MQTT_CA'))
        self.client.on_message=self._on_message
        self.client.on_connect=self._on_connect
    def _on_connect(self,client,userdata,flags,reason,properties):
        if reason==0:
            for topic,callback,qos in self.callbacks: client.subscribe(topic,qos=qos)
    def _on_message(self,client,userdata,message):
        if len(message.payload)>262144:
            self.dropped+=1
            return
        item=(message.topic,bytes(message.payload),int(time.time()*1000),int(time.monotonic()*1000))
        try: self.queue.put_nowait(item)
        except queue.Full:
            self.dropped+=1
            try:
                receipt=decode(item[0],item[1],item[2]); data=receipt.data
                if data['type'] in {'bedside_check','demo_control'} or data.get('monitor_alarm'):
                    with self.safety_lock:
                        old=self.safety_pending.get(message.topic)
                        if old is None or data['ts']>=json.loads(old[1])['ts']:
                            self.safety_pending[message.topic]=item
            except ValueError: pass
    def subscribe(self,topic,callback,qos=1): self.callbacks.append((topic,callback,qos))
    def connect(self):
        self.client.connect(os.environ.get('SW_MQTT_HOST','localhost'),int(os.environ.get('SW_MQTT_PORT','1883')),60)
        self.client.loop_start()
    def drain(self,limit=4096):
        import paho.mqtt.client as mqtt
        with self.safety_lock:
            pending=list(self.safety_pending.values()); self.safety_pending.clear()
        for topic,payload,received,mono in pending:
            for pattern,callback,qos in self.callbacks:
                if mqtt.topic_matches_sub(pattern,topic): callback(topic,payload,received_ms=received,received_mono_ms=mono)
        for _ in range(limit):
            try: topic,payload,received,mono=self.queue.get_nowait()
            except queue.Empty: break
            for pattern,callback,qos in self.callbacks:
                if mqtt.topic_matches_sub(pattern,topic): callback(topic,payload,received_ms=received,received_mono_ms=mono)
    def publish(self,topic,data,qos=1,retain=False):
        info=self.client.publish(topic,encode(topic,data),qos=qos,retain=retain)
        if info.rc: raise RuntimeError(f'MQTT publish failed: {info.rc}')
    def close(self): self.client.disconnect(); self.client.loop_stop()
