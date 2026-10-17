"""Offline dynsec config generation for Mosquitto 2.0.18; no secret argv."""
import base64
import hashlib
import secrets

from sw_common.topics import ALL_SUB

DEVICES = tuple(f'MON-{i:02d}' for i in range(1,13))
SERVICES = ('simulator','brain','backend','agents','attacks','extractor')
CONTROL = '$CONTROL/dynamic-security/v1'


def credentials():
    return {name:secrets.token_urlsafe(36) for name in ('admin', *DEVICES, *SERVICES)}


def acl(kind, topic):
    return {'acltype':kind, 'topic':topic, 'allow':True, 'priority':0}


def role(name, publish=(), subscribe=()):
    acls = [acl('publishClientSend',topic) for topic in publish]
    for topic in subscribe:
        acls.extend([acl('subscribePattern',topic), acl('publishClientReceive',topic)])
    return {'rolename':name,'acls':acls}


def roles():
    vitals = tuple(f'ward/bed/B{i:02d}/vitals' for i in range(1,13))
    return [
        role('admin',(CONTROL,), (CONTROL+'/response',)),
        *(role(f'monitor-{i:02d}',(topic,)) for i,topic in enumerate(vitals,1)),
        # Simulator control account deliberately CANNOT publish any vitals.
        role('simulator',(),('ward/demo/control',)),
        role('brain',('ward/bed/+/score/+','ward/bed/+/verdict'),
             ('ward/bed/+/vitals','net/device/+/features','ward/bed/+/bedside','ward/demo/control')),
        role('backend',('ward/request','ward/demo/control','ward/action','ward/bed/+/bedside'),ALL_SUB),
        role('agents',('ward/action','ward/alert','ward/record','ward/bed/+/bedside'),
             ('ward/request','ward/bed/+/verdict','ward/bed/+/bedside',
              'ward/bed/+/score/M3','ward/bed/+/score/M5','ward/demo/control','ward/action','ward/alert')),
        # Deliberate demo attacker; never grant verdict/feature/control/admin writes.
        role('attacks',vitals,('ward/bed/+/vitals','ward/demo/control')),
        role('extractor',('net/device/+/features',),('ward/bed/+/vitals','ward/demo/control')),
    ]


def build_config(secrets_by_user):
    clients=[]
    for name,password in secrets_by_user.items():
        salt=secrets.token_bytes(12)
        # Mosquitto v2.0.18 password_mosq.h/c: PBKDF2-HMAC-SHA512,
        # 12-byte salt, 64-byte key, default 101 iterations. Random 288-bit passwords.
        encoded=base64.b64encode(hashlib.pbkdf2_hmac('sha512',password.encode(),salt,101,64)).decode()
        rolename='monitor-'+name[-2:] if name in DEVICES else name
        client={'username':name,'password':encoded,'salt':base64.b64encode(salt).decode(),
                'iterations':101,'roles':[{'rolename':rolename,'priority':0}]}
        if name in DEVICES:
            client['clientid']=name
        clients.append(client)
    return {'defaultACLAccess':{'publishClientSend':False,'publishClientReceive':False,'subscribe':False,'unsubscribe':True},
            'clients':clients,'roles':roles(),'groups':[]}


def service_env(service, values):
    if service not in SERVICES: raise ValueError('Unknown service')
    common={'SW_MQTT_USER':service,'SW_MQTT_PASS':values[service]}
    if service in ('backend','simulator'):
        return {**common,'MQTT_HOST':'127.0.0.1','MQTT_PORT':'1883','MQTT_USER':service,'MQTT_PASS':values[service]}
    prefix={'brain':'SW_MQTT_','attacks':'SW_ATTACK_MQTT_','agents':'SENTINEL_MQTT_','extractor':'SW_MQTT_'}[service]
    result={**common,prefix+'HOST':'127.0.0.1',prefix+'PORT':'1883',prefix+'USERNAME':service,prefix+'PASSWORD':values[service]}
    if service == 'agents':
        result.update(SENTINEL_MQTT_TLS='false', SENTINEL_MQTT_CLIENT_ID='sw-agents')
    elif service in ('brain','attacks'):
        result[prefix+'TLS']='0'
    return result
