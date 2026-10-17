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
    assert out[0]['score'] < .5 and not out[0]['extra']['drift_growing']


def test_m6_steady_offset_is_watched_not_paged():
    # B11 live run 4: no usable early cuff (prior 0), one later cuff 9 mmHg off scored ~0.6 (UNSURE page).
    _, out = m6_run([(948000, 94, 85)])
    assert out[0]['extra']['baseline_source'] == 'clinical_prior'
    assert out[0]['score'] == PressureDrift.STEADY_CAP and not out[0]['extra']['drift_growing']
    assert out[0]['reason'] == 'Steady line/cuff offset +9 mmHg; watching'
    # The same steady offset on later cuffs is still not drift.
    _, out = m6_run([(600000, 94, 85), (750000, 94.5, 85), (900000, 94, 85)])
    assert all(r['score'] < .5 for r in out)
    # An early-learned usual gap: a steady 12 mmHg step from it is watched too.
    _, out = m6_run([(60000, 75, 80), (120000, 75, 80), (700000, 87, 80), (850000, 87, 80)])
    assert all(r['score'] < .5 for r in out[2:]) and 'watching' in out[3]['reason']


def test_m6_single_very_large_gap_asks_for_relevel():
    _, out = m6_run([(531000, 84, 66)])  # 18 mmHg off on one cuff
    assert out[0]['score'] == PressureDrift.LARGE_GAP_SCORE
    assert 'large gap: re-level and re-check' in out[0]['reason']
    _, out = m6_run([(531000, 81, 66)])  # exactly 15 mmHg
    assert out[0]['score'] == PressureDrift.LARGE_GAP_SCORE
    # A large gap that then grows is drift (>= .8), as before.
    _, out = m6_run([(531000, 84, 66), (665000, 87, 66)])
    assert out[1]['score'] >= .8 and out[1]['extra']['drift_growing']


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


def test_m6_early_pairs_learn_despite_ecg_problems_but_not_with_a_second_sender():
    for sender, learned in ((None, True), ('second', False)):
        detector = PressureDrift()
        state = SimpleNamespace(messages=[], network=None, last_message=None, alarm_until_ms=0,
                                patient_not_ok=False, baseline_admission_allowed=False)  # e.g. M1 flat ECG
        frame = {'ts': 60000, 'abp': [86.] * 125, 'nibp': {'map': 80, 'ts': 60000}}
        state.messages = [{'message': frame, 'received_ms': 60000, 'sender_id': 'first'},
                          {'message': dict(frame, ts=60500, nibp=None), 'received_ms': 60500, 'sender_id': sender}]
        detector({'bed_id': 'B09', 'window_start': 51000}, state, 61000)
        assert bool(detector.baselines['B09']) is learned


# --- confirmed low pressure (cuff < 65, line agrees within tolerance, held until recovery) ---

from sw_brain.detectors import confirmed_low_pressure


def lp_feed(state, seconds, line, cuff_at=None, start=0):
    """Append 1 s frames; line(t) gives the line mean; cuff_at maps second -> cuff MAP. Returns held per second."""
    held = []
    for t in range(start, start + seconds):
        cuff = (cuff_at or {}).get(t)
        message = {'ts': t * 1000, 'abp': [float(line(t))] * 125,
                   'nibp': None if cuff is None else {'map': cuff, 'sys': cuff + 30, 'dia': cuff - 15, 'ts': t * 1000}}
        state.messages.append({'message': message, 'received_ms': t * 1000 + 50})
        state.last_message = message
        held.append(confirmed_low_pressure(state, t * 1000 + 100))
    return held


def test_low_pressure_confirms_when_line_agrees_within_tolerance():
    state = BedState('B09')
    held = lp_feed(state, 30, lambda t: 68, {5: 57})  # line 68: above 65 but within tolerance
    assert not any(held[:5]) and all(held[5:])
    state = BedState('B09')
    assert not any(lp_feed(state, 30, lambda t: 74, {5: 57}))  # line clearly disagrees: not confirmed
    state = BedState('B09')
    assert not any(lp_feed(state, 30, lambda t: 60, {5: 70}))  # normal cuff: not confirmed


def test_low_pressure_holds_across_65_crossings_between_cuffs():
    state = BedState('B09')
    wobble = lambda t: (62, 66, 69, 73, 64, 67)[t % 6]  # B09-like: line hovers 61-76 around 65
    held = lp_feed(state, 600, wobble, {10: 57})
    first = held.index(True)
    assert first <= 12 and all(held[first:])  # one continuous episode, never dropped at 65


def test_low_pressure_releases_after_60s_recovery_or_new_normal_cuff():
    state = BedState('B09')
    line = lambda t: 62 if t < 100 else 75
    held = lp_feed(state, 200, line, {5: 57})
    assert all(held[5:100])
    assert all(held[100:155])          # recovering, not yet 60 s (10 s mean crosses 70 at ~t=104)
    assert not any(held[170:])         # line >= 70 for 60 s: released
    state = BedState('B09')
    held = lp_feed(state, 120, lambda t: 62, {5: 57, 60: 66})
    assert all(held[5:60]) and not held[60]  # a new cuff >= 65 releases at once (line alone 62 cannot re-confirm)
    assert not any(held[60:])


def test_low_pressure_needs_a_fresh_cuff_to_confirm():
    state = BedState('B09')
    held = lp_feed(state, 400, lambda t: 74 if t < 350 else 62, {5: 57})  # line falls only after the cuff expired
    assert not any(held)
