"""M6 line-vs-cuff drift (early baseline, growth, re-zero) and the held low-pressure confirmation."""
from types import SimpleNamespace

from sw_brain.extended import PressureDrift
from sw_brain.service import BedState


def m6_run(pairs, bed='B08', first_ts=0):
    """pairs: (cuff_ts_ms, line_mmHg, cuff_map). Returns the M6 result after each cuff."""
    detector = PressureDrift()
    state = SimpleNamespace(messages=[], network=None, last_message=None)
    start = {'ts': first_ts, 'abp': [80.] * 125, 'nibp': None}
    state.messages = [{'message': start, 'received_ms': first_ts}]
    detector({'bed_id': bed, 'window_start': first_ts - 9000}, state, first_ts + 1000)  # bed starts here
    out = []
    for ts, line, cuff in pairs:
        frame = {'ts': ts, 'abp': [float(line)] * 125, 'nibp': {'map': cuff, 'sys': cuff + 30, 'dia': cuff - 15, 'ts': ts}}
        state.messages = [{'message': frame, 'received_ms': ts}]
        out.append(detector({'bed_id': bed, 'window_start': ts - 9000}, state, ts + 1000))
    return detector, out


def test_m6_learns_usual_gap_only_from_early_pairs():
    # Two early cuffs (first 5 min) set usual -5; a later shifted cuff is scored, never learned.
    detector, out = m6_run([(60000, 75, 80), (120000, 75, 80), (700000, 85, 80), (900000, 85, 80)])
    assert out[0]['score'] is None and out[0]['extra']['baseline_warming']
    assert list(detector.baselines['B08']) == [-5., -5.]
    assert out[2]['extra']['baseline_gap_mmhg'] == -5. and out[2]['extra']['baseline_source'] == 'early_pairs'
    assert out[3]['extra']['baseline_gap_mmhg'] == -5.  # the drifted cuffs did not become the new normal


def test_m6_no_early_cuff_uses_clinical_prior_and_is_eligible_at_first_cuff():
    # B08's real shape: first cuff after the line already started drifting (T+08:51).
    _, out = m6_run([(531000, 68.6, 66)])
    assert out[0]['extra']['baseline_source'] == 'clinical_prior'
    assert out[0]['extra']['baseline_gap_mmhg'] == 0.
    assert out[0]['extra']['eligible'] and 0 < out[0]['score'] < .5  # rising, not yet a verdict


def test_m6_growing_gap_past_margin_crosses_point_eight():
    # B08 cuffs: gap +2.6, +8.5, +10.8 with the cuff roughly level.
    _, out = m6_run([(531000, 68.6, 66), (665000, 75.5, 67), (817000, 85.8, 75)])
    assert out[0]['score'] < .5
    assert out[1]['score'] >= .8 and out[1]['extra']['drift_growing']
    assert 'growing' in out[1]['reason'] and 're-zero' in out[1]['reason']
    assert out[2]['score'] >= .8


def test_m6_one_off_gap_without_growth_stays_below_point_eight():
    _, out = m6_run([(531000, 74, 66)])  # one cuff 8 mmHg off: no trend yet
    assert .5 <= out[0]['score'] < .8 and not out[0]['extra']['drift_growing']


def test_m6_both_pressures_falling_is_not_drift():
    # Line and cuff fall together (B09-like); a growing gap while the cuff itself falls is not drift.
    _, out = m6_run([(60000, 90, 82), (120000, 90, 82), (400000, 82, 70), (550000, 75, 58)])
    assert all(r['score'] < .8 for r in out[2:])
    assert not out[3]['extra']['drift_growing']


def test_m6_rezero_clears_to_normal_at_next_cuff():
    _, out = m6_run([(531000, 68.6, 66), (665000, 75.5, 67), (817000, 85.8, 75), (970000, 74.6, 77)])
    assert out[2]['score'] >= .8
    assert out[3]['score'] < .5 and not out[3]['extra']['drift_growing']
    # Near the learned early baseline also clears.
    _, out = m6_run([(60000, 75, 80), (120000, 75, 80), (700000, 82, 80), (800000, 85, 80), (900000, 76, 80)])
    assert out[3]['score'] >= .8
    assert out[4]['score'] < .2


def test_m6_implausible_early_gap_is_not_learned():
    detector, _ = m6_run([(40000, 10, 75)])  # -65 mmHg: line not usable as a reference
    assert not detector.baselines['B08']
