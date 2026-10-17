import base64
import hashlib
import json
import subprocess
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sw_sec.policy import build_config, credentials, service_env
from sw_sec.containment import Containment
from sw_sec.features import Extractor, LogTail
from sw_sec.io import private_write
from sw_common import validate, make_vitals


def test_monitor_acl_and_no_default_receive_leak():
    secret = credentials()
    config = build_config(secret)
    assert config['defaultACLAccess'] == {'publishClientSend':False,'publishClientReceive':False,'subscribe':False,'unsubscribe':True}
    roles = {r['rolename']:r['acls'] for r in config['roles']}
    clients = {c['username']:c for c in config['clients']}
    assert len([u for u in clients if u.startswith('MON-')]) == 12
    assert roles['monitor-03'] == [{'acltype':'publishClientSend','topic':'ward/bed/B03/vitals','allow':True,'priority':0}]
    assert clients['MON-03']['clientid'] == 'MON-03'
    assert clients['simulator']['roles'] == [{'rolename':'simulator','priority':0}]
    salt = base64.b64decode(clients['MON-03']['salt'])
    assert base64.b64decode(clients['MON-03']['password']) == hashlib.pbkdf2_hmac('sha512',secret['MON-03'].encode(),salt,101,64)
    assert not any(a['topic'].startswith('$CONTROL') for r in config['roles'] if r['rolename'] != 'admin' for a in r['acls'])


def test_env_names_match_consumers():
    values = credentials()
    assert service_env('backend',values)['MQTT_USER'] == 'backend'
    assert service_env('simulator',values)['MQTT_USER'] == 'simulator'
    assert service_env('brain',values)['SW_MQTT_PASSWORD'] == values['brain']
    assert service_env('attacks',values)['SW_ATTACK_MQTT_USERNAME'] == 'attacks'
    assert service_env('agents',values)['SW_MQTT_PASS'] == values['agents']


def test_private_writes_refuse_symlinks_and_keep_600(tmp_path):
    path = tmp_path/'secret'
    private_write(path,'one')
    private_write(path,'two')
    assert path.stat().st_mode & 0o777 == 0o600
    link = tmp_path/'link'
    link.symlink_to(path)
    with pytest.raises(ValueError): private_write(link,'oops')
    assert path.read_text() == 'two'


def test_containment_validation_dry_run_and_confirmed_state(tmp_path):
    options = tmp_path/'ctrl.conf'
    private_write(options,'-u admin\n-P hidden-secret\n')
    calls=[]
    disabled=False
    def run(argv, **kwargs):
        nonlocal disabled
        calls.append(argv)
        assert kwargs.get('shell',False) is False
        if 'disableClient' in argv: disabled=True
        if 'enableClient' in argv: disabled=False
        output = 'Username: MON-03\nClientid: MON-03\nDisabled: '+str(disabled).lower()+'\n'
        return subprocess.CompletedProcess(argv,0,output,'')
    helper=Containment(options,tmp_path/'audit.jsonl',run=run)
    for name in ['MON-03;id','MON-00','MON-13','MON-3','MON-03\n','backend']:
        with pytest.raises(ValueError): helper.disable_client(name)
    helper.disable_client('MON-03',dry_run=True)
    assert not calls
    helper.disable_client('MON-03')
    assert helper.disabled('MON-03')
    helper.enable_client('MON-03')
    assert not helper.disabled('MON-03')
    assert all('hidden-secret' not in str(c) for c in calls)
    assert 'hidden-secret' not in (tmp_path/'audit.jsonl').read_text()


def test_control_stderr_errors_and_timeout_fail_closed(tmp_path):
    path=tmp_path/'options'; private_write(path,'-u admin\n')
    helper=Containment(path,tmp_path/'audit',run=lambda *a,**kw:subprocess.CompletedProcess(a,0,'','Error: not authorised'))
    with pytest.raises(RuntimeError): helper.disable_client('MON-03')


def test_features_rates_jitter_replay_and_null_unknowns():
    e=Extractor()
    e.observe('ward/bed/B03/vitals',json.dumps(make_vitals(bed_id='B03',device_id='MON-03',seq=1,ts=10000,fs=125,ecg=[0.0]*125,ppg=[1.0]*125,abp=None,hr=None,spo2=None,rr=None)).encode(),10000)
    e.observe('ward/bed/B03/vitals',json.dumps(make_vitals(bed_id='B03',device_id='MON-03',seq=3,ts=11000,fs=125,ecg=[0.0]*125,ppg=[1.0]*125,abp=None,hr=None,spo2=None,rr=None)).encode(),11000)
    e.observe('ward/bed/B03/vitals',json.dumps(make_vitals(bed_id='B03',device_id='MON-03',seq=3,ts=11000,fs=125,ecg=[0.0]*125,ppg=[1.0]*125,abp=None,hr=None,spo2=None,rr=None)).encode(),12000)
    e.observe('ward/bed/B03/vitals',b'broken',13000)
    message=e.snapshot('MON-03',10000)
    assert validate(message,strict=True) == []
    assert message['msgs_per_s'] == .8
    assert message['iat_mean_ms'] == 1000
    assert message['iat_std_ms'] == 0
    assert message['seq_gaps'] == 1 and message['seq_repeats'] == 1
    assert message['malformed'] == 1
    assert message['stale_ms'] == 4000
    assert message['senders'] is None and message['connects_per_s'] is None
    unknown=e.snapshot('MON-04',10000)
    assert unknown['msgs_per_s'] == 0
    assert unknown['iat_mean_ms'] is None and unknown['stale_ms'] is None


def test_log_connect_publish_attribution_rotation_and_missing(tmp_path):
    e=Extractor(); path=tmp_path/'mosquitto.log'; tail=LogTail(path,e,clock=lambda:0)
    tail.poll()
    assert not e.logs_available
    path.touch(); tail.poll()  # Attach at EOF before the live broker appends.
    path.write_text("10: New client connected from 127.0.0.1:123 as MON-03 (p2, c1, k30, u'MON-03').\n10: Received PUBLISH from MON-03 (d0, q0, r0, m0, 'ward/bed/B03/vitals', ... (80 bytes))\n10: New connection from 127.0.0.1:123 on port 1883.\n")
    tail.poll()
    msg=e.snapshot('MON-03',10000)
    assert msg['senders'] == 1 and msg['connects_per_s'] == .2
    path.rename(tmp_path/'old'); path.write_text('11: Client <unknown> disconnected, not authorised.\n')
    tail.poll()
    assert e.unattributed_auth_failures == 1


def test_ctrl_enabled_client_omits_disabled_and_loopback_warning_is_not_failure(tmp_path):
    from sw_sec.containment import UNENCRYPTED_WARNING
    options=tmp_path/'options'; private_write(options,'-h 127.0.0.1\n')
    helper=Containment(options,tmp_path/'audit',run=lambda *a,**kw:subprocess.CompletedProcess(a,0,'Username: MON-03\nClientid: MON-03\nRoles: monitor-03 (priority: 0)\n',UNENCRYPTED_WARNING))
    assert helper.disabled('MON-03') is False


def test_clean_session_revokes_data_acl_before_temporary_enable_and_restores_disabled(tmp_path):
    options=tmp_path/'options';private_write(options,'-u admin\n')
    calls=[]; disabled=False; role=True
    def run(argv,**kwargs):
        nonlocal disabled,role
        command=argv[4]; calls.append(command)
        if command=='disableClient': disabled=True
        if command=='enableClient':
            assert not role  # Temporary authentication has no data permissions.
            disabled=False
        if command=='removeClientRole': role=False
        if command=='addClientRole':
            assert argv[-1]=='0'
            assert disabled
            role=True
        out=f'Username: MON-03\nClientid: MON-03\nDisabled: {str(disabled).lower()}\nRoles: '+('monitor-03' if role else '')+'\n'
        return subprocess.CompletedProcess(argv,0,out,'')
    def connect(*args):
        assert not disabled and not role
        calls.append('clean-connect')
    helper=Containment(options,tmp_path/'audit',run=run)
    helper.clean_session('MON-03','never-in-argv',connect=connect)
    assert disabled and role
    assert calls.index('removeClientRole')<calls.index('enableClient')<calls.index('clean-connect')<calls.index('addClientRole')


def test_new_demo_run_resets_sequence_baseline_and_duplicate_controls_do_not():
    from sw_common import make_demo_control
    e=Extractor()
    def observed(seq,ts):
        e.observe('ward/bed/B03/vitals',json.dumps(make_vitals(bed_id='B03',device_id='MON-03',seq=seq,ts=ts,fs=125,ecg=[0.0]*125,ppg=[1.0]*125,abp=None,hr=None,spo2=None,rr=None)).encode(),ts)
    observed(900,10000)
    control=make_demo_control(cmd='run',run_id='fresh',start_at_s=0,ts=15000)
    e.control(control)
    observed(1,15000)
    e.control(control)
    observed(1,16000)
    window=e.snapshot('MON-03',15000)
    assert window['seq_gaps']==0 and window['seq_repeats']==1


def test_root_verification_can_read_private_service_owned_env(tmp_path,monkeypatch):
    from sw_sec.io import private_read
    import sw_sec.io
    path=tmp_path/'env'; private_write(path,'MQTT_USER=backend\n')
    monkeypatch.setattr(sw_sec.io.os,'geteuid',lambda:0)
    assert private_read(path)=='MQTT_USER=backend\n'


def test_rotated_log_leaves_partial_window_sender_count_unknown(tmp_path):
    ticks=[9000]
    path=tmp_path/'log'
    path.touch()
    e=Extractor();tail=LogTail(path,e,clock=lambda:ticks[0])
    tail.poll()
    path.write_text("10: Received PUBLISH from MON-03 (d0, q0, r0, m0, 'ward/bed/B03/vitals', ... (80 bytes))\n")
    tail.poll()
    assert e.snapshot('MON-03',10000)['senders']==1
    ticks[0]=12000
    path.rename(tmp_path/'old')
    path.write_text('12: broker log rotated\n')
    tail.poll()
    assert e.snapshot('MON-03',10000)['senders'] is None


def test_sender_set_overflow_is_unknown_not_a_fabricated_exact_count():
    e=Extractor();e.logs_available=True
    for index in range(1025):
        e.log(f"10: Received PUBLISH from sender-{index} (d0, q0, r0, m0, 'ward/bed/B03/vitals', ... (80 bytes))")
    assert e.snapshot('MON-03',10000)['senders'] is None
