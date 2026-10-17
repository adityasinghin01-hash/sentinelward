"""M3 regressions on the ward's observed patient waveforms, without synthetic attacks in clean cases.

Set SW_M3_PACKS to a packs-v13 directory on CI. Local ward packs are discovered
when present; portable synthetic M3 tests remain in test_live_extended.py.
"""
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sw_brain.extended import BodyMismatch

PACKS = Path(os.environ.get('SW_M3_PACKS', '/Users/aditya/Desktop/sentinelward/.work/packs-v13'))
pytestmark = pytest.mark.skipif(not (PACKS / 'B01.npz').exists(), reason='SW_M3_PACKS real ward data unavailable')


@pytest.fixture(scope='module')
def packs():
    return {p.stem: dict(np.load(p)) for p in PACKS.glob('B*.npz')}


def observe(model, packs, bed, sec, pulse_bed=None, pulse_sec=None, admit=True, patient_ok_ts=-1):
    data = packs[bed]
    pulse = packs[pulse_bed or bed]
    ps = sec if pulse_sec is None else pulse_sec
    window = dict(bed_id=bed, window_start=sec*1000,
                  ecg=data['ecg'][sec*125:(sec+10)*125].tolist(),
                  ppg=pulse['ppg'][round(ps*125):round((ps+10)*125)].tolist())
    state = SimpleNamespace(baseline_admission_allowed=admit, patient_ok_ts=patient_ok_ts,
                            last_message={'hr':float(np.nanmedian(data['hr'][sec:sec+10]))})
    return model(window, state, (sec+10)*1000)


@pytest.mark.parametrize('bed,sec', [('B01',150),('B02',150),('B03',30),('B05',1000),('B11',190),('B12',600)])
def test_real_ppg_half_rate_is_rechecked_not_body_mismatch(packs, bed, sec):
    model = BodyMismatch()
    observations = [observe(model,packs,bed,sec)]
    assert all(r['score'] is not None and r['score'] < .5 for r in observations), observations
    assert any('alias' in r['reason'].lower() for r in observations)


@pytest.mark.parametrize('bed', ['B01','B02','B06','B08','B10','B12'])
def test_real_clean_usable_windows_do_not_lock_to_wrong_pat_pair(packs, bed):
    model = BodyMismatch()
    values = [observe(model,packs,bed,s) for s in range(0,1191,5)]
    checked = [r for r in values[6:] if r['score'] is not None]
    assert sum(r['score'] < .5 for r in checked)/len(checked) >= .9


@pytest.mark.parametrize('donor', ['B06','B08','B10'])
def test_different_patients_pulse_remains_high(packs, donor):
    model = BodyMismatch()
    for sec in range(30,90,5):
        observe(model,packs,'B01',sec)
    results = [observe(model,packs,'B01',sec,pulse_bed=donor) for sec in range(90,120,5)]
    assert max((r['score'] or 0.) for r in results[1:]) >= .8, results
    assert sum((r['score'] or 0.) >= .8 for r in results[1:]) >= 3


@pytest.mark.parametrize('shift', [3,4,5,6,7])
def test_same_patients_time_shifted_pulse_remains_high(packs, shift):
    model = BodyMismatch()
    for sec in range(30,90,5):
        observe(model,packs,'B01',sec)
    results = [observe(model,packs,'B01',sec,pulse_sec=sec-shift) for sec in range(90,120,5)]
    assert max((r['score'] or 0.) for r in results[1:]) >= .8, results
    assert sum((r['score'] or 0.) >= .8 for r in results[1:]) >= 3


def test_frozen_pulse_window_remains_high(packs):
    model = BodyMismatch()
    for sec in range(30,90,5):
        observe(model,packs,'B01',sec)
    results = [observe(model,packs,'B01',sec,pulse_sec=80) for sec in range(90,130,5)]
    assert all(r['score'] >= .8 for r in results[2:]), results


def test_flat_frozen_pulse_remains_high(packs):
    data = dict(packs['B06'])
    data['ppg'] = np.full_like(data['ppg'], data['ppg'][30*125])
    model = BodyMismatch()
    assert observe(model,{**packs,'B06':data},'B06',30)['score'] >= .8

@pytest.mark.parametrize('shift', [3.2,4.2,6.2,7.2])
def test_fractional_pulse_shifts_remain_high(packs, shift):
    model = BodyMismatch()
    for sec in range(30,90,5):
        observe(model,packs,'B01',sec)
    results = [observe(model,packs,'B01',sec,pulse_sec=sec-shift) for sec in range(90,120,5)]
    assert all(r['score'] >= .8 for r in results[1:]), results


def test_pulse_replay_evidence_does_not_spread_into_recovered_live_data(packs):
    model = BodyMismatch()
    changed = {**packs, 'B01': dict(packs['B01'])}
    changed['B01']['ppg'] = packs['B01']['ppg'].copy()
    changed['B01']['ppg'][95*125:100*125] = packs['B01']['ppg'][85*125:90*125]
    values = [observe(model,changed,'B01',sec,patient_ok_ts=180000 if sec >= 180 else -1) for sec in range(30,230,5)]
    assert any(r['score'] >= .8 for r in values)
    assert all(r['score'] < .5 for r in values[-6:])


def test_irregular_donor_pulse_does_not_establish_normal(packs):
    model = BodyMismatch()
    for sec in range(60,120,5):
        observe(model,packs,'B01',sec)
    values = [observe(model,packs,'B01',sec,pulse_bed='B02') for sec in range(120,150,5)]
    assert any(r['score'] is None or r['score'] >= .8 for r in values[1:]), values
    assert all(not r['extra'].get('not_applicable', False) for r in values)


def test_real_b11_nonharmonic_rate_disagreement_is_preserved(packs):
    # This region is not an alias: pulse 88 bpm vs ECG/monitor about 67 bpm.
    model = BodyMismatch()
    values = [observe(model,packs,'B11',sec) for sec in (145,150)]
    assert values[-1]['score'] >= .8


def test_frozen_pulse_cannot_outwait_replay_hold(packs):
    model = BodyMismatch()
    for sec in range(30,90,5):
        observe(model,packs,'B01',sec)
    results = [observe(model,packs,'B01',sec,pulse_sec=80) for sec in range(90,1190,5)]
    assert all((r['score'] or 0.) >= .8 for r in results[2:]), results


@pytest.mark.parametrize('shift', [3,4,5,6,7,3.2,7.2])
def test_sustained_pulse_shift_cannot_train_itself_away(packs, shift):
    model = BodyMismatch()
    for sec in range(30,90,5):
        observe(model,packs,'B01',sec)
    values = [observe(model,packs,'B01',sec,pulse_sec=sec-shift) for sec in range(90,1190,5)]
    assert all((r['score'] or 0.) >= .8 for r in values[2:]), values


@pytest.mark.parametrize('sec', [65, 85, 225, 635])
def test_observed_low_amplitude_pulses_can_resolve_missed_peak_rate(packs, sec):
    model = BodyMismatch()
    observation = observe(model, packs, 'B02', sec)
    assert observation['score'] is not None and observation['score'] < .5, observation
    assert observation['extra'].get('pulse_peak_agreement', 0) >= .7


@pytest.mark.parametrize('bed,sec', [('B04',280), ('B09',50), ('B12',620),
                                  ('B04',185), ('B07',165)])
def test_usable_but_unpairable_ecg_pauses_in_real_clinical_windows(packs, bed, sec):
    from sw_brain.detectors import QualityDetector
    data = packs[bed]
    w = dict(ecg=data['ecg'][sec*125:(sec+10)*125], ppg=data['ppg'][sec*125:(sec+10)*125])
    assert QualityDetector().evaluate(w, None, 0)['score'] < .5
    observation = observe(BodyMismatch(), packs, bed, sec)
    assert observation['score'] is None
    assert observation['extra']['not_applicable'] is True


def test_known_pulse_replay_cannot_be_erased_by_irregular_ecg(packs):
    model = BodyMismatch()
    for sec in range(30,90,5):
        observe(model,packs,'B01',sec)
    for sec in range(90,120,5):
        replay = observe(model,packs,'B01',sec,pulse_sec=80)
    assert replay['score'] >= .8
    changed = {**packs, 'B01': dict(packs['B01'])}
    changed['B01']['ecg'] = packs['B01']['ecg'].copy()
    changed['B01']['ecg'][120*125:130*125] = packs['B04']['ecg'][30*125:40*125]
    observation = observe(model,changed,'B01',120,pulse_sec=80)
    assert observation['score'] >= .8
    assert not observation['extra'].get('not_applicable', False)


@pytest.mark.parametrize('sec', [85, 100])
def test_b11_clipped_pulse_at_part_rate_is_detection_alias_not_body_mismatch(packs, sec):
    # Live judged run: ECG 61-62 = monitor HR, clipped PPG read at 19-30 bpm, M3 scored up to 1.0.
    model = BodyMismatch()
    for s in range(30, sec, 5):
        observe(model, packs, 'B11', s)
    r = observe(model, packs, 'B11', sec)
    assert r['score'] is not None and r['score'] < .5, r
    assert 'unreliable' in r['reason'].lower() or 'alias' in r['reason'].lower(), r['reason']


def test_b11_with_another_patients_pulse_still_scores_high(packs):
    model = BodyMismatch()
    for s in range(30, 90, 5):
        observe(model, packs, 'B11', s)
    scores = [observe(model, packs, 'B11', s, pulse_bed='B06')['score'] for s in range(90, 130, 5)]
    assert sum(x is not None and x >= .8 for x in scores) >= 3, scores
