"""Rollback tests use real files; only service manager is external/faked."""
import json
import os
from pathlib import Path
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sw_sec.deploy import Snapshot, render_config
from sw_sec.launch import MonitorBus, AgentBroker


def test_snapshot_restores_bytes_permissions_and_absent_files_twice(tmp_path):
    old=tmp_path/'old'; new=tmp_path/'new'
    old.write_text('anonymous demo\n'); old.chmod(0o640)
    snapshot=Snapshot(tmp_path/'backup.json')
    snapshot.capture([old,new])
    old.write_text('hardened'); new.write_text('added')
    snapshot.capture([old,new])  # Never overwrite the first backup.
    snapshot.restore()
    snapshot.restore()
    assert old.read_text()=='anonymous demo\n'
    assert old.stat().st_mode & 0o777 == 0o640
    assert not new.exists()


def test_config_restricts_plain_listener_and_enables_tls(tmp_path):
    config=render_config('/plugin.so',tmp_path)
    assert 'listener 1883 127.0.0.1\n' in config
    assert 'listener 8883 0.0.0.0\n' in config
    assert 'allow_anonymous false\n' in config
    assert 'log_dest' not in config
    assert 'publish' not in config


def test_simulator_separates_control_from_device_connections(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from sw_sec.io import private_write
    private_write(tmp_path/'devices',json.dumps({'MON-03':'secret-three','MON-05':'secret-five'}))
    monkeypatch.setenv('SW_MONITOR_CREDENTIALS',str(tmp_path/'devices'))
    records=[]
    class Bus:
        def __init__(self,host,port,client_id,**options): self.id=client_id; records.append((client_id,options))
        def connect(self,**kw): return True
        def publish(self,message): return self.id==message['device_id']
        def close(self): pass
    mux=MonitorBus(SimpleNamespace(mqtt_host='127.0.0.1',mqtt_port=1883,mqtt_user='simulator',mqtt_pass='control-secret'),'sw_sim',bus_factory=Bus)
    assert mux.publish({'type':'vitals','bed_id':'B03','device_id':'MON-03'})
    assert mux.publish({'type':'vitals','bed_id':'B05','device_id':'MON-05'})
    assert [row[0] for row in records] == ['sw_sim','MON-03','MON-05']
    assert records[1][1]['username']=='MON-03'
    with pytest.raises(ValueError): mux.publish({'type':'vitals','bed_id':'B05','device_id':'MON-03'})
    mux.close()


@pytest.fixture
def server(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from sw_sec import deploy
    import sw_sec.mqtt_probe
    from sw_sec.io import private_write
    root=tmp_path
    uid=os.geteuid();gid=os.getegid()
    user=SimpleNamespace(pw_uid=uid,pw_gid=gid,pw_dir=str(root),pw_name='demo')
    monkeypatch.setattr(deploy.os,'geteuid',lambda:0)
    monkeypatch.setattr(deploy.os,'chown',lambda *a:None)
    monkeypatch.setattr(deploy.pwd,'getpwnam',lambda _:user)
    monkeypatch.setattr(deploy.shutil,'which',lambda name:'/usr/bin/'+name)
    monkeypatch.setattr(deploy,'private_read',lambda path:Path(path).read_text())
    monkeypatch.setattr(deploy,'BROKER_DIR',root/'broker')
    monkeypatch.setattr(deploy,'SITE',root/'hub.conf')
    monkeypatch.setattr(deploy,'SYSTEMD_DIR',root/'systemd')
    monkeypatch.setattr(deploy.time,'sleep',lambda _:None)
    private_write(root/'hub.conf','original anonymous demo\n',mode=0o644)
    private_write(root/'plugin.so','test fixture')
    calls=[]
    def run(argv,**kw):
        calls.append(argv)
        output=''
        if '--property=LoadState' in argv:
            output='not-found' if 'rollback' in argv[2] or argv[2]=='sw-net.service' else 'loaded'
        elif '--property=ActiveState' in argv: output='active'
        elif 'getDefaultACLAccess' in argv: output='publishClientReceive: deny\n'
        return subprocess.CompletedProcess(argv,0,output,'')
    monkeypatch.setattr(deploy,'run_checked',run)
    def tls(directory,state,ip):
        for path in (directory/'ca.crt',directory/'server.crt',directory/'server.key',state/'ca.key'):
            private_write(path,'test fixture')
    monkeypatch.setattr(deploy,'generate_tls',tls)
    monkeypatch.setattr(sw_sec.mqtt_probe,'probe',lambda *a,**kw:{'connect':0})
    return deploy,root,calls


def test_provisioning_rerun_preserves_secrets_and_rollback_restores_original(server):
    deploy,root,calls=server
    kwargs=dict(server_ip='127.0.0.1',service_user='demo',state=root/'state',plugin=root/'plugin.so',app=root/'app',venv=root/'venv')
    deploy.setup(**kwargs)
    initial=(root/'state/credentials.json').read_bytes()
    broker=(root/'broker/dynamic-security.json').read_bytes()
    calls.clear()
    deploy.setup(**kwargs)
    assert (root/'state/credentials.json').read_bytes()==initial
    assert (root/'broker/dynamic-security.json').read_bytes()==broker
    assert not any('stop' in call or 'restart' in call for call in calls)
    deploy.rollback(root/'state')
    assert (root/'hub.conf').read_text()=='original anonymous demo\n'
    assert not (root/'systemd/sw-net.service').exists()
    deploy.rollback(root/'state')
    assert (root/'hub.conf').read_text()=='original anonymous demo\n'


def test_failed_service_authentication_rolls_back(server,monkeypatch):
    deploy,root,calls=server
    import sw_sec.mqtt_probe
    monkeypatch.setattr(sw_sec.mqtt_probe,'probe',lambda *a,**kw:{'connect':135})
    with pytest.raises(RuntimeError):
        deploy.setup(server_ip='127.0.0.1',service_user='demo',state=root/'state',plugin=root/'plugin.so',app=root/'app',venv=root/'venv')
    assert (root/'hub.conf').read_text()=='original anonymous demo\n'
    assert (root/'state/status').read_text().strip()=='rolled-back'
    armed=next(i for i,c in enumerate(calls) if c[0]=='systemd-run')
    stopped=next(i for i,c in enumerate(calls) if c[:3]==['systemctl','stop','mosquitto'])
    assert armed<stopped
