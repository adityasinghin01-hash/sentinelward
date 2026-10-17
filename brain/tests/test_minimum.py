import json
import math
import pytest
from sw_brain.io import decode, encode, MemoryBus
from sw_brain.service import BrainService
from sw_brain.decision import decide


def test_schema_preserves_zero_and_null_and_checks_topic(frame):
    msg=frame(ecg=[0]*125, ppg=None)
    assert decode('ward/bed/B01/vitals', json.dumps(msg)).data['ecg'][0] == 0
    assert decode('ward/bed/B01/vitals', json.dumps(msg)).data['ppg'] is None
    for changes in ({'seq':True}, {'fs':True}, {'ecg':[True]*125}, {'ecg':[float('nan')]*125}, {'bed_id':'B02'}, {'hr':'60'}):
        with pytest.raises(ValueError): decode('ward/bed/B01/vitals', json.dumps(frame(**changes)))


def test_all_six_scores_align_and_fault_has_channel(frame):
    bus=MemoryBus(); service=BrainService(bus)
    for i in range(10): service.receive('ward/bed/B01/vitals', json.dumps(frame(i,ecg=[0]*125)), received_ms=i*1000)
    service.tick(10000)
    scores=[m for t,m,q,r in bus.published if '/score/' in t]
    assert len(scores)==6
    assert {s['window_start'] for s in scores}=={0}
    assert all(s['model_version']==s['model']+'-live-2026-10-17' for s in scores)
    m1=next(s for s in scores if s['model']=='M1')
    assert m1['score']>=0.8 and m1['extra']['channel']=='ecg'


def test_monitor_alarm_survives_duplicate_tampering_offline_and_patient_ok(frame):
    bus=MemoryBus(); service=BrainService(bus)
    for i in range(10): service.receive('ward/bed/B01/vitals', json.dumps(frame(i)), received_ms=i*1000)
    service.receive('ward/bed/B01/vitals', json.dumps(frame(9,monitor_alarm={'code':'VTACH','priority':'high'})),received_ms=9500)
    verdict=service.tick(10000)[0]
    assert verdict['verdict']=='BOTH'
    assert service.tick(45000)[0]['verdict'] in {'EMERGENCY','BOTH'}
    service.receive('ward/bed/B01/bedside',json.dumps({'v':1,'type':'bedside_check','bed_id':'B01','ts':46000,'result':'patient_ok','by':'staff:nurse'}),received_ms=46000)
    assert service.tick(50000)[0]['verdict']=='UNSURE'
    assert service.snapshots['B01']['hr']==60


def test_replay_uses_only_nonoverlapping_history_and_is_per_bed(frame):
    bus=MemoryBus(); service=BrainService(bus)
    for i in range(20):
        service.receive('ward/bed/B01/vitals',json.dumps(frame(i)),received_ms=i*1000)
        if i==9: service.tick(10000)
    result=service.tick(20000)[0]
    assert result['scores']['M4']>=0.9
    assert result['verdict']=='TAMPERING'
    for i in range(10): service.receive('ward/bed/B02/vitals',json.dumps(frame(i,bed='B02')),received_ms=10000+i*1000)
    assert next(v for v in service.tick(20000) if v['bed_id']=='B02')['scores']['M4']<0.5


def test_reset_clears_inference_but_keeps_display_snapshot(frame):
    service=BrainService(MemoryBus())
    service.receive('ward/bed/B01/vitals',json.dumps(frame()),received_ms=0)
    service.receive('ward/demo/control',json.dumps({'v':1,'type':'demo_control','ts':1000,'cmd':'reset','run_id':'run_x','start_at_s':0}),received_ms=1000)
    assert not service.beds
    assert service.snapshots['B01']['hr']==60


@pytest.mark.parametrize('expected,overrides',[
 ('NORMAL',{}),('EMERGENCY',{'alarm':True}),('BOTH',{'alarm':True,'M4':.99}),
 ('TAMPERING',{'M4':.99}),('DRIFTING',{'M6':.95}),('LOOSE_SENSOR',{'M1':.95}),
 ('DEVICE_ATTACK',{'M5':.95}),('UNSURE',{'offline':True})])
def test_first_match_all_verdicts_and_numeric_trust(expected,overrides):
    scores={f'M{i}':{'score':.05,'reason':'clean','extra':{'eligible':True}} for i in range(1,7)}
    alarm=overrides.pop('alarm',False); offline=overrides.pop('offline',False)
    for model,value in overrides.items(): scores[model]={'score':value,'reason':'suspicious','extra':{'eligible':True,'independent_evidence':True}}
    result=decide('B01',0,10000,scores,alarm=alarm,offline=offline)
    assert result['verdict']==expected
    assert isinstance(result['confidence'],float) and isinstance(result['trust'],float)
    assert result['trust']==pytest.approx(1-max(scores[m]['score'] for m in ('M3','M4','M5')))


def test_saved_m2_threshold_preserves_research_emergency_and_no_line_normal():
    scores={f'M{i}':{'score':.05,'reason':'clean','extra':{'eligible':True}} for i in range(1,7)}
    scores['M2']={'score':.62,'reason':'VTACH supported','extra':{'eligible':True,'positive':True,'threshold':.61}}
    assert decide('B01',0,10000,scores)['verdict']=='EMERGENCY'
    scores['M2']={'score':.05,'reason':'clean','extra':{'eligible':True,'positive':False}}
    scores['M6']={'score':None,'reason':'No arterial line','extra':{'eligible':False,'no_arterial_line':True}}
    assert decide('B01',0,10000,scores)['verdict']=='NORMAL'


def test_second_sender_alone_is_uncertain_not_tampering(frame):
    bus=MemoryBus(); service=BrainService(bus)
    for i in range(10): service.receive('ward/bed/B01/vitals',json.dumps(frame(i)),received_ms=i*1000,sender_id='monitor')
    service.receive('ward/bed/B01/vitals',json.dumps(frame(10)),received_ms=10000,sender_id='new_sender')
    value=service.tick(10000)[0]
    assert .5<=value['scores']['M4']<.8
    assert value['verdict']=='UNSURE'
