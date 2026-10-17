import json
from pathlib import Path
import pytest
from sw_brain.io import MemoryBus, decode
from sw_attacks.service import AttackService
from sw_attacks.schedule import load_schedule


def control(service,ts=0,start=0,cmd='run',run_id='test'):
    return service.receive('ward/demo/control',json.dumps({'v':1,'type':'demo_control','ts':ts,'cmd':cmd,'run_id':run_id,'start_at_s':start}),received_ms=ts)


def capture(service,message,received_ms=None):
    return service.receive('ward/bed/'+message['bed_id']+'/vitals',json.dumps(message),received_ms=message['ts'] if received_ms is None else received_ms)


def events(tmp_path,run_id='test'):
    path=tmp_path/run_id/'events.jsonl'
    return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []


def test_doc12_schedule_and_disclosed_defaults():
    specs={s['id']:s for s in load_schedule()}
    assert set(specs)=={'replay_B05','flatline_B06','mixed_B07','drift_B10','network_B11','sender_B12'}
    assert (specs['replay_B05']['start_s'],specs['replay_B05']['source_start_s'],specs['replay_B05']['end_s'])==(600,360,930)
    assert (specs['mixed_B07']['start_s'],specs['mixed_B07']['end_s'])==(825,870)
    assert (specs['sender_B12']['start_s'],specs['sender_B12']['end_s'])==(1020,1040)
    assert specs['flatline_B06']['end_basis']=='implementation_default'
    assert specs['network_B11']['end_basis']=='implementation_default'
    assert specs['drift_B10']['ramp_s']==420


def test_replay_captures_while_idle_retains_source_values_seq_ts_and_ignores_echo(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    source=frame(360)
    capture(service,source)
    control(service)
    service.tick(600000)
    assert len(bus.published)==1
    topic,message,qos,retain=bus.published[0]
    assert message==source and qos==0 and retain is False
    before=len(service.history['B05'])
    assert capture(service,message,600001) is False
    assert len(service.history['B05'])==before
    rows=[r for r in events(tmp_path) if r['bed_id']=='B05']
    assert [r['event'] for r in rows]==['attack_start','second_sender_on']
    assert rows[0]['t_s']==600


def test_seek_needs_actual_history_and_reports_unavailable_without_success(tmp_path):
    service=AttackService(MemoryBus(),runs_dir=tmp_path)
    control(service,ts=1000000,start=610)
    service.tick(1000000)
    rows=events(tmp_path)
    assert [row['event'] for row in rows]==['attack_unavailable','attack_unavailable'] # B10 and B05 are active at seek.
    assert all(row['t_s']==610 for row in rows)
    assert not any(row['event']=='attack_start' for row in rows)


def test_fixture_enables_seek_and_rebases_original_source_interval(tmp_path,frame):
    fixture=tmp_path/'fixture.jsonl'
    fixture.write_text(json.dumps({'t_s':370,'message':frame(370)})+'\n')
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path/'runs',fixtures=fixture)
    control(service,ts=1000000,start=610)
    service.tick(1000000)
    replay=next(m for _,m,_,_ in bus.published if m['bed_id']=='B05')
    assert replay['ts']==760000 and replay['seq']==370
    assert replay['ecg']==frame(370)['ecg']


def test_flatline_and_drift_are_full_frames_and_preserve_original_source(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    original=frame(960,bed='B06'); capture(service,original)
    control(service,ts=960000,start=960)
    service.tick(960000)
    flat=next(m for _,m,_,_ in bus.published if m['bed_id']=='B06')
    assert flat['ecg']==[0.]*125 and flat['ppg']==original['ppg']
    assert flat['monitor_alarm']=={'code':'ASYSTOLE','priority':'high'}
    assert original['ecg']!=[0.]*125
    capture(service,frame(961,bed='B10'))
    service.tick(961000)
    drift=next(m for _,m,_,_ in bus.published if m['bed_id']=='B10')
    assert drift['abp'][0]==pytest.approx(frame(961,bed='B10')['abp'][0]+15)
    for topic,message,qos,retain in bus.published: decode(topic,json.dumps(message))


def test_pressure_ramp_is_relative_to_documented_start_and_stops_at_end(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    control(service)
    for t,offset in ((360,0),(570,7.5),(780,15),(1199,15)):
        capture(service,frame(t,bed='B10'))
        service.tick(t*1000)
        message=next(m for _,m,_,_ in reversed(bus.published) if m['bed_id']=='B10')
        assert message['abp'][0]-frame(t,bed='B10')['abp'][0]==pytest.approx(offset)
    before=len(bus.published); service.tick(1200000)
    assert len(bus.published)==before


def test_flood_is_bounded_and_does_not_catch_up_after_pause(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    control(service)
    capture(service,frame(720,bed='B11'))
    service.tick(720000)
    capture(service,frame(725,bed='B11'))
    service.tick(725000)
    assert len(bus.published)==2
    for now in range(725020,730001,20): service.tick(now)
    messages=[m for _,m,_,_ in bus.published if m['bed_id']=='B11']
    assert 2<=len(messages)<=500
    assert not any(t.startswith('ward/bed/B01/') for t,_,_,_ in bus.published)
    rows=events(tmp_path)
    assert any(e['event']=='flood_start' for e in rows)
    assert any(e['event']=='scan_unavailable' for e in rows)
    assert any(e['event']=='attack_end' and e['bed_id']=='B11' for e in rows)


def test_exact_20s_sender_window_and_reset_end_pairing(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    control(service,ts=1020000,start=1020)
    for sec in range(1020,1041):
        capture(service,frame(sec,bed='B12'))
        service.tick(sec*1000)
    assert len([m for _,m,_,_ in bus.published if m['bed_id']=='B12'])==20
    rows=events(tmp_path)
    assert next(e for e in rows if e['event']=='attack_start')['t_s']==1020
    assert next(e for e in rows if e['event']=='attack_end')['t_s']==1040
    control(service,ts=1041000,cmd='reset')
    assert not service.running and not service.history
    before=len(bus.published); service.tick(1050000); assert len(bus.published)==before


def test_reset_interrupts_active_attacks_logs_actual_times_and_rejects_stale_control(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    capture(service,frame(360)); control(service); service.tick(600000)
    control(service,ts=601250,cmd='reset')
    row=next(e for e in events(tmp_path) if e['event']=='attack_end')
    assert row['t_s']==601.25 and row['ts']==601250 and 'reset' in row['detail']
    assert control(service,ts=0) is False
    assert not service.running


def test_publish_failure_never_logs_success_and_retry_can_start(tmp_path,frame):
    class Failing(MemoryBus):
        def publish(self,*args,**kwargs): raise RuntimeError('broker down')
    bus=Failing(); service=AttackService(bus,runs_dir=tmp_path)
    capture(service,frame(360)); control(service); service.tick(600000)
    assert not any(e['event']=='attack_start' for e in events(tmp_path))
    assert any(e['event']=='attack_unavailable' for e in events(tmp_path))
    bus.publish=MemoryBus.publish.__get__(bus)
    capture(service,frame(361)); service.tick(601000)
    assert any(e['event']=='attack_start' for e in events(tmp_path))


def test_event_keys_sanitization_and_duplicate_control(tmp_path,frame):
    service=AttackService(MemoryBus(),runs_dir=tmp_path)
    capture(service,frame(360)); assert control(service)
    assert control(service) is False
    assert control(service,ts=1,run_id='../../escape') is False
    service.tick(600000)
    for row in events(tmp_path):
        assert set(row)=={'run_id','t_s','ts','bed_id','event','detail'}
        assert row['run_id']=='test' and row['ts']==600000


def test_full_virtual_1200s_schedule_is_finite_and_pairs_started_attacks(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    control(service)
    for sec in range(1201):
        for bed in ('B05','B06','B07','B10','B11','B12'):
            if bed!='B07' or 540<=sec<870: capture(service,frame(sec,bed=bed))
        service.tick(sec*1000)
    rows=events(tmp_path)
    starts=[e['bed_id'] for e in rows if e['event']=='attack_start']
    ends=[e['bed_id'] for e in rows if e['event']=='attack_end']
    assert set(starts)=={'B05','B06','B07','B10','B11','B12'}
    assert sorted(starts)==sorted(ends)
    assert not service.running
    assert all(len(m['ecg'])==len(m['ppg'])==125 for _,m,_,_ in bus.published)


def test_real_50hz_bursts_cannot_exceed_500_messages_and_leave_monitor_source_unchanged(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    control(service,ts=720000,start=720)
    originals={}
    for now in range(720000,731000,20):
        if now%1000==0:
            source=frame(now//1000,bed='B11'); originals[source['ts']]=source
            capture(service,source)
        service.tick(now)
    sent=[m for _,m,_,_ in bus.published if m['bed_id']=='B11']
    assert len(sent)==500
    assert all(m==originals[m['ts']] for m in sent)


def test_new_run_interrupts_old_run_and_fixture_shape_is_validated(tmp_path,frame):
    service=AttackService(MemoryBus(),runs_dir=tmp_path)
    capture(service,frame(360)); control(service); service.tick(600000)
    control(service,ts=601000,run_id='next')
    assert any(e['event']=='attack_end' and 'new run' in e['detail'] for e in events(tmp_path))
    fixture=tmp_path/'bad.jsonl'
    fixture.write_text(json.dumps({'t_s':360,'message':frame(360,ecg=[1])})+'\n')
    with pytest.raises(ValueError): AttackService(MemoryBus(),runs_dir=tmp_path,fixtures=fixture)


def test_b07_burst_then_sender_ends_at_source_boundary(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    control(service,ts=825000,start=825)
    for now in range(825000,871001,20):
        if now%1000==0 and now<870000: capture(service,frame(now//1000,bed='B07'))
        service.tick(now)
    sent=[m for _,m,_,_ in bus.published if m['bed_id']=='B07']
    assert 400<len(sent)<=500
    assert max(m['ts'] for m in sent)<870000
    end=next(e for e in events(tmp_path) if e['event']=='attack_end' and e['bed_id']=='B07')
    assert end['ts']==870000


def test_non_second_control_timestamp_replays_nearest_actual_source_frame(tmp_path,frame):
    bus=MemoryBus(); service=AttackService(bus,runs_dir=tmp_path)
    # Controls carry arbitrary epoch milliseconds; vitals are on the epoch second grid.
    source=frame(360); capture(service,source)
    control(service,ts=123,start=0)
    service.tick(600123)
    replay=next(m for _,m,_,_ in bus.published if m['bed_id']=='B05')
    assert replay==source


@pytest.mark.parametrize('field,value',[('steady_rate_hz',100),('steady_rate_hz',True),('burst_s',-1),('burst_s',1000),('max_messages',True)])
def test_custom_flood_schedule_cannot_bypass_bounds(tmp_path,field,value):
    import yaml
    source=Path(__file__).resolve().parents[1]/'schedule.yaml'
    data=yaml.safe_load(source.read_text())
    mixed=next(s for s in data['attacks'] if s['id']=='mixed_B07')
    mixed[field]=value
    path=tmp_path/'unbounded.yaml'; path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError): load_schedule(path)


def test_same_run_newer_delivery_cannot_reset_origin_or_flood_budget(tmp_path):
    service=AttackService(MemoryBus(),runs_dir=tmp_path)
    control(service,run_id='same')
    service.states['network_B11']['count']=500
    assert control(service,ts=721000,run_id='same') is False
    assert service.origin_ms==0
    assert service.states['network_B11']['count']==500


@pytest.mark.parametrize('corruption', ['missing', 'nonfinite', 'device'])
def test_invalid_attack_output_is_counted_logged_and_never_sent(tmp_path, frame, monkeypatch, caplog, corruption):
    import sw_attacks.service as module
    bus = MemoryBus(); service = AttackService(bus, runs_dir=tmp_path)
    capture(service, frame(360)); control(service)
    def broken_transform(spec, source, script_s):
        message = dict(source)
        if corruption == 'missing': del message['nibp']
        elif corruption == 'nonfinite': message['extra'] = {'bad': float('nan')}
        else: message['device_id'] = 'MON-03'
        return message
    monkeypatch.setattr(module, 'transform', broken_transform)
    service.tick(600000)
    assert not bus.published
    assert service.invalid_outgoing == 1
    assert 'Rejected outgoing attack message' in caplog.text
    assert not any(row['event'] == 'attack_start' for row in events(tmp_path))
    assert any(row['event'] == 'attack_unavailable' for row in events(tmp_path))


def test_invalid_attack_input_is_counted_and_does_not_pollute_history(tmp_path, frame):
    service = AttackService(MemoryBus(), runs_dir=tmp_path)
    assert not capture(service, frame(device_id='MON-03'))
    assert service.invalid_incoming == 1
    assert not service.history


def test_transport_drop_never_records_success(tmp_path, frame):
    class Dropping(MemoryBus):
        def publish(self, *args, **kwargs): return False
    service = AttackService(Dropping(), runs_dir=tmp_path)
    capture(service, frame(360)); control(service); service.tick(600000)
    assert service.states['replay_B05']['count'] == 0
    assert not any(row['event'] == 'attack_start' for row in events(tmp_path))
    assert any(row['event'] == 'attack_unavailable' for row in events(tmp_path))


def test_replacing_run_cannot_forge_from_previous_run_source(tmp_path, frame):
    bus = MemoryBus(); service = AttackService(bus, runs_dir=tmp_path)
    assert control(service, run_id='old')
    capture(service, frame(999, bed='B06'))
    assert control(service, ts=1000000, start=960, run_id='new')
    service.tick(1000000)
    assert not any(message['bed_id'] == 'B06' for _, message, _, _ in bus.published)
    capture(service, frame(1001, bed='B06', seq=1))
    service.tick(1001000)
    assert any(message['bed_id'] == 'B06' for _, message, _, _ in bus.published)
    service.close(1002000)
