import itertools
import json
from types import SimpleNamespace

import pytest

from sw_brain.decision import decide
from sw_brain.io import MemoryBus
from sw_brain.service import BrainService


def test_alarm_preserved_for_every_high_low_detector_combination():
    for flags in itertools.product((0.,1.),repeat=6):
        results={f'M{i+1}':{'score':value,'reason':'observed','extra':{'eligible':True,'independent_evidence':True}} for i,value in enumerate(flags)}
        for offline in (False,True):
            verdict=decide('B01',0,10000,results,alarm=True,offline=offline)
            assert verdict['verdict'] in {'EMERGENCY','BOTH'}
            assert verdict['priority']=='high'


def test_old_timestamp_replay_after_seek_still_reaches_detector(frame):
    service=BrainService(MemoryBus())
    control={'v':1,'type':'demo_control','ts':600000,'cmd':'run','run_id':'seek','start_at_s':600}
    service.receive('ward/demo/control',json.dumps(control),received_ms=600000)
    service.receive('ward/bed/B01/vitals',json.dumps(frame(600)),received_ms=600000)
    service.receive('ward/bed/B01/vitals',json.dumps(frame(360)),received_ms=601000)
    assert service.tick(605000)[0]['scores']['M4']>=.9


def test_quality_nulls_clipping_mains_and_high_frequency_noise():
    import numpy as np
    from sw_brain.detectors import QualityDetector
    detector=QualityDetector(); t=np.arange(1250)/125
    for bad in ([None]*1250, [12.]*1250, np.sin(2*np.pi*50*t).tolist(), ([1.]*625+[-1.]*625)):
        window={'ecg':bad,'ppg':(500+100*np.sin(2*np.pi*t)).tolist()}
        result=detector.evaluate(window,None,10000)
        assert result['score']>=.8
        assert result['extra']['channel']=='ecg'


def test_natural_end_and_late_join_are_not_attacks(frame):
    service=BrainService(MemoryBus())
    for i in range(300,310): service.receive('ward/bed/B03/vitals',json.dumps(frame(i,bed='B03')),received_ms=i*1000)
    service.tick(310000)
    verdict=service.tick(330000)[0]
    assert verdict['verdict']=='UNSURE'
    assert verdict['scores']['M4']<.5 and verdict['scores']['M5']<.5
    service.receive('ward/bed/B07/vitals',json.dumps(frame(540,bed='B07')),received_ms=540000)
    assert next(v for v in service.tick(545000) if v['bed_id']=='B07')['verdict']=='UNSURE'


def test_missing_channel_is_quality_fault_but_never_zero_filled(frame):
    service=BrainService(MemoryBus())
    for i in range(10): service.receive('ward/bed/B01/vitals',json.dumps(frame(i,ecg=None)),received_ms=i*1000)
    state=service.beds['B01']
    assert all(v is None for v in state.windows[-1]['ecg'])
    assert not any(state.windows[-1]['ecg_valid'])
    verdict=service.tick(10000)[0]
    assert verdict['scores']['M1']==1.
    assert verdict['verdict']=='UNSURE'


@pytest.mark.parametrize('updates',[{'bed_id':[]},{'device_id':{}},{'type':[]},{'monitor_alarm':{'code':[],'priority':'high'}},{'hr':10**1000}])
def test_malformed_json_never_crashes_service(frame,updates):
    service=BrainService(MemoryBus())
    assert service.receive('ward/bed/B01/vitals',json.dumps(frame(**updates)),received_ms=10000) is False


def test_repeated_alarm_frames_keep_first_prealarm_window(frame):
    service=BrainService(MemoryBus())
    for i in range(13):
        alarm={'code':'VTACH','priority':'high'} if i>=10 else None
        service.receive('ward/bed/B01/vitals',json.dumps(frame(i,monitor_alarm=alarm)),received_ms=i*1000)
    assert service.beds['B01'].prealarm_window['window_start']==0


def test_network_suspect_windows_cannot_train_pat_baseline():
    import numpy as np
    from sw_brain.detectors import DetectorSuite
    from sw_brain.service import BedState
    suite=DetectorSuite(); state=BedState('B01')
    t=np.arange(1250)/125
    ecg=sum(np.exp(-((t-s)/.02)**2) for s in np.arange(.3,10,.8))
    ppg=sum(np.exp(-((t-s-.2)/.05)**2) for s in np.arange(.3,10,.8))
    for k in range(4):
        now=(k+1)*10000
        state.messages.clear()
        for i in range(20): state.messages.append({'message':{'seq':0,'ts':now-1000},'received_ms':now-1000+i,'payload_bytes':100,'sender_id':'attacker','sequence_issue':True})
        window={'bed_id':'B01','window_start':k*10000,'ecg':ecg.tolist(),'ppg':ppg.tolist(),'monitor_alarms':[]}
        suite.evaluate(window,state,now)
    assert len(suite.detectors['M3'].baselines['B01'])==0


def test_iat_uses_monotonic_receipts_across_wall_clock_adjustment(frame):
    service=BrainService(MemoryBus())
    for i in range(10):
        # A wall-clock correction changes packet timestamps but not real packet spacing.
        wall=100000+i*1000
        service.receive('ward/bed/B01/vitals',json.dumps(frame(i)),received_ms=wall,received_mono_ms=200000+i*1000)
    result=service.suite.detectors['M5'].evaluate(None,service.beds['B01'],110000)
    assert result['extra']['features']['inter_arrival_mean']==1.


def test_offline_preserves_higher_priority_established_drift():
    results={f'M{i}':{'score':.05,'reason':'clear','extra':{'eligible':True}} for i in range(1,7)}
    results['M6']['score']=.95
    assert decide('B08',0,10000,results,offline=True)['verdict']=='DRIFTING'
