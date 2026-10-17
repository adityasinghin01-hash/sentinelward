"""Explicit server acceptance checks. Run only between demos with producers stopped."""
import json
import socket
import ssl
import time
import threading
from paho.mqtt import client as mqtt
from pathlib import Path
from .containment import Containment
from .io import private_read, private_write
from .mqtt_probe import probe


def run_live(service_state, evidence, *, host='127.0.0.1', tls_host='127.0.0.1'):
    root=Path(service_state)
    devices=json.loads(private_read(root/'devices.json'))
    options=root/'admin.conf'
    helper=Containment(options,root/'live-audit.jsonl')
    rows=[]
    def check(name,operation):
        try:
            passed=operation() is True
            rows.append((name,'PASS' if passed else 'FAIL'))
        except Exception:
            # Neither broker diagnostics nor credentials enter evidence/stdout.
            rows.append((name,'FAIL'))
    device='MON-03'; password=devices[device]
    def monitor(**kw): return probe(host,1883,username=device,password=password,client_id=device,**kw)
    check('Valid monitor can connect',lambda:monitor()['connect']==0)
    check('Valid own-bed QoS1 publish accepted',lambda:monitor(topic='ward/bed/B03/vitals')['publish'] in (0,16))
    check('Anonymous publish rejected',lambda:probe(host,1883,topic='ward/bed/B03/vitals')['connect'] in (134,135))
    check('Wrong password rejected',lambda:probe(host,1883,username=device,password='invalid-'+password,client_id=device)['connect'] in (134,135))
    check('MON-03 cannot publish B05',lambda:monitor(topic='ward/bed/B05/vitals')['publish']==135)
    check('Monitor subscription rejected',lambda:monitor(topic='ward/bed/B03/vitals',subscribe=True)['subscribe']==[135])
    initial=None
    persistent=None
    try:
        initial=helper.disabled(device)
        # Do not alter an already-contained device as part of an acceptance test.
        if initial: raise RuntimeError('Monitor is already disabled; choose a maintenance window')
        connected=threading.Event(); kicked=threading.Event()
        persistent=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=device,protocol=mqtt.MQTTv5)
        persistent.username_pw_set(device,password)
        persistent.reconnect_delay_set(min_delay=30,max_delay=30)
        persistent.on_connect=lambda c,u,f,r,p:connected.set() if not r.is_failure else None
        persistent.on_disconnect=lambda c,u,f,r,p:kicked.set()
        persistent.connect(host,1883,keepalive=10); persistent.loop_start()
        if not connected.wait(5): raise RuntimeError('Persistent monitor did not authenticate')
        helper.disable_client(device)
        check('Connected monitor kicked on disable',lambda:kicked.wait(5))
        check('Disconnected monitor cannot queue QoS0 publish',lambda:persistent.publish('ward/bed/B03/vitals',b'{}',qos=0).rc==mqtt.MQTT_ERR_NO_CONN)
        persistent.disconnect(); persistent.loop_stop(); persistent=None
        check('Disabled monitor reconnect rejected',lambda:monitor()['connect'] in (134,135))
        check('Disabled monitor publish blocked',lambda:monitor(topic='ward/bed/B03/vitals')['connect'] in (134,135))
        helper.clean_session(device,password)
        check('Session wiped, still disabled',lambda:helper.disabled(device))
    except Exception:
        rows.append(('Containment and session cleanup','FAIL'))
    finally:
        if persistent is not None:
            persistent.disconnect(); persistent.loop_stop()
        if initial is False:
            try:
                helper.enable_client(device)
                check('Re-enabled own-bed publish accepted',lambda:monitor(topic='ward/bed/B03/vitals')['publish'] in (0,16))
            except Exception:
                rows.append(('Re-enable recovery','FAIL'))
    def tls():
        context=ssl.create_default_context(cafile=str(root/'ca.crt'))
        with socket.create_connection((tls_host,8883),timeout=5) as plain:
            with context.wrap_socket(plain,server_hostname=tls_host) as secure:
                return secure.version() in ('TLSv1.2','TLSv1.3')
    check('TLS handshake and CA/SAN verification',tls)
    check('Authenticated MQTT over TLS',lambda:probe(tls_host,8883,username=device,password=password,client_id=device,ca=root/'ca.crt')['connect']==0)
    def no_plain():
        with socket.create_connection((tls_host,8883),timeout=5) as plain:
            plain.settimeout(5)
            # Complete MQTT 3.1.1 CONNECT with no credentials, as raw cleartext.
            plain.sendall(b'\x10\x0e\x00\x04MQTT\x04\x02\x00\x0a\x00\x02sw')
            try: return plain.recv(4)==b''
            except ConnectionResetError: return True
            # A timeout is inconclusive, not evidence of TLS enforcement.
    check('Plain MQTT on 8883 rejected',no_plain)
    text='| Security check | Result |\n|---|---|\n'+''.join(f'| {name} | {result} |\n' for name,result in rows)
    directory=Path(evidence); directory.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    private_write(directory/(stamp+'-security.md'),text)
    private_write(directory/(stamp+'-security.json'),json.dumps({'utc':stamp,'checks':[{'name':n,'result':r} for n,r in rows]},indent=2))
    print(text)
    return all(result=='PASS' for _,result in rows)
