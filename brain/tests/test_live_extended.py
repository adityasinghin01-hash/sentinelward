from types import SimpleNamespace

import numpy as np
import pytest

from sw_brain.extended import BodyMismatch, PressureDrift, NetworkAttack


def waves(delay_ms=200, ecg_rate=75, ppg_rate=75, start=0, bed='B01'):
    t = np.arange(1250) / 125
    ecg = sum(np.exp(-((t - s) / .018) ** 2) for s in np.arange(.3, 10, 60/ecg_rate))
    ppg = sum(np.exp(-((t - s - delay_ms/1000) / .045) ** 2) for s in np.arange(.3, 10, 60/ppg_rate))
    return dict(bed_id=bed, window_start=start, ecg=ecg.tolist(), ppg=ppg.tolist())


def state(messages=(), network=None):
    return SimpleNamespace(messages=list(messages), network=network, last_message=None)


def test_m3_uses_this_beds_baseline_and_explains_arrival_shift():
    model = BodyMismatch()
    for i in range(4):
        result = model(waves(start=i*10000), state(), i*10000+10000)
    assert result['score'] < .2
    model(waves(delay_ms=480, start=40000), state(), 50000)  # one window alone is not enough
    shifted = model(waves(delay_ms=480, start=50000), state(), 60000)  # persists: 2 of the last 3
    assert shifted['score'] > .8
    assert 'usual' in shifted['reason']
    assert 180 <= shifted['extra']['baseline_pat_ms'] <= 220
    other = model(waves(delay_ms=480, start=40000, bed='B02'), state(), 50000)
    assert other['extra']['baseline_pat_ms'] is None
    assert other['extra']['baseline_warming'] is True
    assert other['score'] < .2  # rates agree; timing is not compared until this bed has a baseline


def test_m3_flat_ecg_with_present_pulse_and_rate_disagreement():
    model = BodyMismatch()
    window = waves()
    window['ecg'] = [0.] * 1250
    assert model(window, state(), 10000)['score'] >= .9
    assert model(waves(ppg_rate=110), state(), 10000)['score'] >= .8


def test_m6_relative_gap_and_only_new_cuffs_update_baseline():
    detector = PressureDrift()
    bed = state()
    def sample(cuff_ts, pressure, bed_id='B08'):
        frame = {'abp': [pressure]*125, 'nibp': {'map':80, 'sys':120, 'dia':60, 'ts':cuff_ts}, 'ts':cuff_ts}
        bed.messages = [{'message':frame, 'received_ms':cuff_ts, 'payload_bytes':100,'sender_id':None}]
        bed.last_message = frame
        return detector({'bed_id':bed_id,'window_start':cuff_ts-9000}, bed, cuff_ts+1000)
    assert sample(10000, 100)['score'] is None
    assert sample(10000, 100)['extra']['baseline_samples'] == 1
    normal = sample(20000, 100)
    assert normal['score'] is None  # two observations establish the baseline for the next cuff
    assert sample(30000, 115)['score'] >= .9
    assert sample(40000, 100)['score'] < .1
    assert sample(50000, 115, 'B09')['score'] is None  # no cross-patient baseline


def test_m6_no_arterial_line_null_and_both_pressures_fall_not_drift():
    detector = PressureDrift()
    assert detector({'bed_id':'B01'}, state(), 10000)['score'] is None
    bed = state()
    for ts, pressure, cuff in [(10000,90,80),(20000,90,80),(30000,65,55)]:
        frame = {'abp':[pressure]*125,'nibp':{'map':cuff,'ts':ts},'ts':ts}
        bed.messages = [{'message':frame,'received_ms':ts,'payload_bytes':100,'sender_id':None}]
        bed.last_message = frame
        result = detector({'bed_id':'B09'}, bed, ts)
    assert result['score'] < .1


def records(count=10, repeat=False, senders=False):
    return [{'message':{'seq':0 if repeat else i, 'ts': i*1000},
             'received_ms':i*1000,'payload_bytes':100+i,
             'sender_id': 'second' if senders and i%2 else 'first'} for i in range(count)]


def test_m5_receipt_rules_normal_flood_repeats_and_sender_evidence():
    detector = NetworkAttack()
    assert detector({'bed_id':'B01','device_id':'MON-01'}, state(records()), 10000)['score'] < .2
    duplicate = detector({'bed_id':'B01'}, state(records(repeat=True)),10000)
    assert duplicate['score'] >= .8
    assert duplicate['extra']['path'] == 'received_rules'
    assert duplicate['extra']['features']['seq_dup_count'] == 9
    assert detector({'bed_id':'B01'}, state(records(senders=True)),10000)['score'] == .6
    flood = records(100)
    for i, entry in enumerate(flood): entry['received_ms'] = i*90
    assert detector({'bed_id':'B01'},state(flood),10000)['score'] >= .9


@pytest.mark.parametrize('field,value,want', [('msgs_per_s', 20, .95),
                                               ('seq_repeats', 3, .9), ('senders', 2, .6),
                                               ('seq_gaps', 10, 0.), ('stale_ms', 9000, 0.)])
def test_m5_fresh_topic7_features_augment_receipt_rules(field, value, want):
    network = {'device_id':'MON-01','window_start':5000,'window_s':5,
               'msgs_per_s':1,'iat_mean_ms':1000,'iat_std_ms':0,'payload_mean':100,
               'payload_std':0,'seq_gaps':0,'seq_repeats':0,'senders':1,'received_ms':10000}
    network[field] = value
    result = NetworkAttack()({'bed_id':'B01','device_id':'MON-01'},state(records(),network),10000)
    assert result['score'] == want
    assert result['extra']['path'] == 'received_and_topic7_rules'
    assert result['extra']['topic7_features'][field] == value
    assert result['extra']['features']['inter_arrival_mean'] == 1
    assert 'research' not in result['extra']


@pytest.mark.parametrize('start', [-5000, 10000])
def test_m5_stale_or_future_topic7_features_cannot_raise_score(start):
    network = {'device_id':'MON-01','window_start':start,'window_s':5,
               'msgs_per_s':100,'seq_repeats':5,'senders':2}
    result = NetworkAttack()({'device_id':'MON-01'},state(records(),network),10000)
    assert result['score'] == 0.
    assert result['extra']['path'] == 'received_rules'


def test_m5_fresh_extractor_evidence_works_without_local_receipts():
    network = {'device_id':'MON-01','window_start':5000,'window_s':5,
               'msgs_per_s':100,'seq_repeats':0,'senders':1}
    result = NetworkAttack()({'device_id':'MON-01'},state([],network),10000)
    assert result['score'] == .95
    assert result['extra']['path'] == 'topic7_rules'


def test_integrated_six_live_scores_include_null_warmup_and_no_line(frame):
    from sw_brain.io import MemoryBus
    from sw_brain.service import BrainService
    import json
    bus = MemoryBus()
    service = BrainService(bus)
    for i in range(10):
        service.receive('ward/bed/B01/vitals',json.dumps(frame(i)),received_ms=i*1000)
    verdict = service.tick(10000)[0]
    assert all(isinstance(verdict['scores'][m],float) for m in ('M1','M4','M5'))
    assert verdict['scores']['M2'] is None
    assert verdict['scores']['M3'] is not None  # rate agreement checked while the timing baseline warms
    assert verdict['scores']['M6'] is None
    assert verdict['verdict'] == 'NORMAL'  # a learning bed with agreeing signals does not raise an alert


def test_drifting_plus_network_is_tampering_and_low_cuff_is_emergency():
    from sw_brain.decision import decide
    from sw_brain.detectors import EmergencyDetector, confirmed_low_pressure
    values = {f'M{i}':{'score':.05,'reason':'clean','extra':{'eligible':True}} for i in range(1,7)}
    values['M5']['score'] = values['M6']['score'] = .95
    assert decide('B10',0,10000,values)['verdict'] == 'TAMPERING'
    bed = state()
    bed.last_message = {'abp':[62.]*125,'nibp':{'map':57,'ts':10000}}
    bed.last_alarm_code=None; bed.alarm_until_ms=0; bed.prealarm_window=None
    bed.patient_ok_ts=-1
    emergency = EmergencyDetector().evaluate(waves(),bed,10000)
    assert emergency['score'] is None
    assert emergency['extra']['not_applicable'] is True
    assert confirmed_low_pressure(bed,10000) is True
    values['M2'] = emergency
    assert decide('B10',0,10000,values,confirmed_low_pressure=True)['verdict'] == 'BOTH'


def test_missing_inputs_are_null_and_seq_gaps_alone_not_attack():
    missing = BodyMismatch()(None,state(),10000)
    assert missing['score'] is None
    assert missing['extra']['eligible'] is False
    assert missing['extra']['unavailable_reason']
    data = records()
    for i,row in enumerate(data): row['message']['seq']=i*3
    observation = NetworkAttack()({'bed_id':'B01'},state(data),10000)
    assert observation['score'] < .5
    assert observation['extra']['features']['seq_gap_count'] == 9


def test_new_alarm_cannot_reuse_old_prealarm_and_stale_bedside_cannot_clear(frame):
    import json
    from sw_brain.io import MemoryBus
    from sw_brain.service import BrainService
    service = BrainService(MemoryBus())
    for i in range(11):
        alarm = {'code':'VTACH','priority':'high'} if i==10 else None
        service.receive('ward/bed/B01/vitals',json.dumps(frame(i,monitor_alarm=alarm)),received_ms=i*1000)
    assert service.beds['B01'].prealarm_window is not None
    service.receive('ward/bed/B01/vitals',json.dumps(frame(30,monitor_alarm={'code':'VTACH','priority':'high'})),received_ms=30000)
    assert service.beds['B01'].prealarm_window is None
    def bedside(ts,result):
        return service.receive('ward/bed/B01/bedside',json.dumps({'v':1,'type':'bedside_check','bed_id':'B01','ts':ts,'result':result,'by':'staff:nurse'}),received_ms=50000)
    bedside(50000,'patient_not_ok')
    bedside(49000,'patient_ok')
    assert service.beds['B01'].patient_not_ok


def test_loose_ecg_is_not_an_emergency_and_last_trusted_snapshot_is_kept(frame):
    import json
    from copy import deepcopy
    from sw_brain.io import MemoryBus
    from sw_brain.service import BrainService
    service = BrainService(MemoryBus())
    for i in range(10): service.receive('ward/bed/B01/vitals',json.dumps(frame(i,ecg=[0.]*125)),received_ms=i*1000)
    verdict=service.tick(10000)[0]
    assert verdict['verdict']=='LOOSE_SENSOR'
    service.last_trusted_snapshots['B01'] = frame(0,hr=62)
    assert service.display_snapshot('B01')['hr']==62


def test_full_mqtt_queue_preserves_alarm_and_reset(frame):
    from types import SimpleNamespace
    import json
    from sw_brain.io import MQTTBus
    bus = MQTTBus(max_queue=1)
    received=[]
    bus.subscribe('ward/bed/+/vitals',lambda topic,payload,**kw: received.append(json.loads(payload)))
    bus.subscribe('ward/demo/control',lambda topic,payload,**kw: received.append(json.loads(payload)))
    def deliver(topic,data): bus.bus._on_message(None,None,SimpleNamespace(topic=topic,payload=json.dumps(data).encode()))
    deliver('ward/bed/B01/vitals',frame(0))
    deliver('ward/bed/B01/vitals',frame(1,monitor_alarm={'code':'VFIB','priority':'high'}))
    deliver('ward/demo/control',{'v':1,'type':'demo_control','ts':2000,'cmd':'reset','run_id':'test','start_at_s':0})
    bus.drain()
    assert any(m.get('monitor_alarm') for m in received)
    assert any(m.get('cmd')=='reset' for m in received)


def test_cuff_persists_to_next_tick_and_reset_rejects_old_controls(frame):
    import json
    from sw_brain.io import MemoryBus
    from sw_brain.service import BrainService
    service=BrainService(MemoryBus())
    for i in range(10):
        cuff={'sys':85,'dia':40,'map':57,'ts':6000} if i==6 else None
        service.receive('ward/bed/B01/vitals',json.dumps(frame(i,abp=[62.]*125,nibp=cuff)),received_ms=i*1000)
    assert service.tick(10000)[0]['verdict']=='EMERGENCY'
    def control(cmd,ts):
        return service.receive('ward/demo/control',json.dumps({'v':1,'type':'demo_control','ts':ts,'cmd':cmd,'run_id':'one','start_at_s':0}),received_ms=ts)
    assert control('reset',20000)
    assert control('run',10000) is False
    assert service.active_run_id is None
    assert service.receive('ward/bed/B01/vitals',json.dumps(frame(21)),received_ms=21000)
    assert service.tick(25000)[0]['verdict']=='UNSURE'


def test_warmup_publishes_all_six_scores_with_null_ineligibility_every_five_seconds(frame):
    import json
    from sw_brain.io import MemoryBus
    from sw_brain.service import BrainService
    bus=MemoryBus()
    service=BrainService(bus)
    service.receive('ward/bed/B01/vitals',json.dumps(frame(0)),received_ms=0)
    for now_ms in (5000, 10000):
        bus.published.clear()
        verdict=service.tick(now_ms)[0]
        assert verdict['verdict']=='UNSURE'
        assert verdict['scores']=={'M1':None,'M2':None,'M3':None,'M4':0.,'M5':0.,'M6':None}
        published_scores=[message for topic,message,_,_ in bus.published if '/score/' in topic]
        assert len(published_scores)==6
        assert {message['model'] for message in published_scores}=={'M1','M2','M3','M4','M5','M6'}
        wire=next(message for topic,message,_,_ in bus.published if topic.endswith('/verdict'))
        assert wire['scores']==verdict['scores']
        for observation in published_scores:
            assert observation['score']==wire['scores'][observation['model']]
            if observation['score'] is None:
                assert observation['extra']['eligible'] is False
                assert observation['extra']['unavailable_reason']
        assert service.invalid_outgoing==0


def test_m3_single_jittery_window_does_not_fire_but_persistent_mismatch_does():
    model = BodyMismatch()
    for i in range(4):
        model(waves(start=i*10000), state(), i*10000+10000)
    once = model(waves(ppg_rate=110, start=40000), state(), 50000)
    assert once['score'] < .5  # one disagreeing window is beat-detection jitter, not an attack
    assert once['extra']['raw_score'] >= .5
    again = model(waves(ppg_rate=110, start=50000), state(), 60000)
    assert again['score'] >= .5  # 2 of the last 3 windows disagree: a real body mismatch


def test_m3_timing_one_beat_apart_is_the_same_timing():
    # At 100 bpm one beat is 600 ms: a pulse measured 648 ms after a beat is the pulse of the
    # previous beat arriving 48 ms after this one, not a 540 ms timing shift.
    model = BodyMismatch()
    for i in range(4):
        model(waves(delay_ms=48, start=i*10000, ecg_rate=100, ppg_rate=100), state(), i*10000+10000)
    later = model(waves(delay_ms=648, start=40000, ecg_rate=100, ppg_rate=100), state(), 50000)
    later = model(waves(delay_ms=648, start=50000, ecg_rate=100, ppg_rate=100), state(), 60000)
    assert later['score'] < .5


def test_m3_new_bed_requires_distinct_windows_for_rate_mismatch():
    model = BodyMismatch()
    first = model(waves(ppg_rate=110), state(), 10000)
    assert first['score'] < .8
    for _ in range(4):
        repeated = model(waves(ppg_rate=110), state(), 10000)
        assert repeated['score'] < .8
    assert model(waves(ppg_rate=110, start=5000), state(), 15000)['score'] >= .8


def test_m3_real_half_rate_pulse_is_not_automatically_an_alias():
    model = BodyMismatch()
    bed = state()
    bed.last_message = {'hr':100}
    for start in (0,5000,10000):
        observation = model(waves(ecg_rate=100,ppg_rate=50,start=start),bed,start+10000)
    assert observation['score'] >= .8


def test_m3_rate_mismatch_persistence_expires_across_a_gap():
    model = BodyMismatch()
    for start in (0,5000):
        model(waves(ppg_rate=110,start=start),state(),start+10000)
    assert model(waves(ppg_rate=110,start=60000),state(),70000)['score'] < .8


@pytest.mark.parametrize('before,after,delay', [(75,120,300),(60,100,350)])
def test_m3_changing_rr_preserves_the_same_physical_arrival(before, after, delay):
    model = BodyMismatch()
    for start in range(0,40000,10000):
        model(waves(ecg_rate=before,ppg_rate=before,delay_ms=delay,start=start),state(),start+10000)
    for start in range(40000,140000,10000):
        observation = model(waves(ecg_rate=after,ppg_rate=after,delay_ms=delay,start=start),state(),start+10000)
        assert observation['score'] < .5


@pytest.mark.parametrize('before,after', [(60,75),(75,100)])
def test_m3_real_arrival_shift_is_not_hidden_by_changing_rr(before, after):
    model = BodyMismatch()
    for start in range(0,40000,10000):
        model(waves(ecg_rate=before,ppg_rate=before,delay_ms=350,start=start),state(),start+10000)
    for start in (40000,50000,60000):
        observation = model(waves(ecg_rate=after,ppg_rate=after,delay_ms=150,start=start),state(),start+10000)
    assert observation['score'] >= .8
