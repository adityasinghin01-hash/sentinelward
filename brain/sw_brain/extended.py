"""Patient-specific live body/pressure checks and receipt-based network witness."""
from __future__ import annotations

from collections import deque
import math
import numpy as np

from .detectors import pulse_metrics, result


class BodyMismatch:
    # A rate/timing disagreement must persist (median of the last 3 windows, i.e. 2 of 3) before it
    # counts as a body mismatch; one jittery window of beat detection must not raise an alert.
    PERSIST = 3

    def __init__(self):
        self.baselines = {}
        self.seen = {}
        self.recent = {}

    def reset(self):
        self.baselines.clear()
        self.seen.clear()
        self.recent.clear()

    def __call__(self, window, state, now_ms):
        if not window:
            return result(None, 'Waiting for ECG and pulse window', eligible=False, path='live_rate_and_pat')
        ecg, ppg = pulse_metrics(window), pulse_metrics(window, 'ppg')
        if ecg is None or ppg is None:
            return result(None, 'Not enough observed ECG and pulse samples', eligible=False, path='live_rate_and_pat')
        rates = {'ecg_rate_bpm':ecg['rate'], 'ppg_rate_bpm':ppg['rate']}
        bed = window['bed_id']
        recent = self.recent.setdefault(bed, deque(maxlen=self.PERSIST))
        if (ecg['rate'] < 20) != (ppg['rate'] < 20):
            # One signal flat while the other beats (fake flatline or a lead off): strong, immediate evidence.
            recent.append(.99)
            return result(.99, 'Heartbeat and pulse disagree: one signal has no usable beats', **rates, path='live_rate_and_pat')
        mismatch = min(1., abs(ecg['rate']-ppg['rate']) / max(20., .25 * max(ecg['rate'],ppg['rate'])))
        pats = []
        for beat in ecg['peaks']:
            after = (ppg['peaks'] - beat) * 8
            after = after[(after >= 80) & (after <= 700)]
            if len(after): pats.append(float(after[0]))
        baseline = self.baselines.setdefault(bed, deque(maxlen=60))
        usual = float(np.median(baseline)) if len(baseline) >= 3 else None
        pat = float(np.median(pats)) if len(pats) >= 3 else None
        # When the pulse takes longer than one beat to reach the finger, it can be paired with the
        # previous or next heartbeat; a difference of exactly one beat interval is the same timing.
        rr_ms = 60000/ecg['rate'] if ecg['rate'] >= 20 else None
        def timing_gap(a, b):
            d = abs(a-b)
            return min(d, abs(a-b-rr_ms), abs(a-b+rr_ms)) if rr_ms else d
        timing_score = min(1., timing_gap(pat, usual)/200) if pat is not None and usual is not None else 0.
        raw = max(mismatch, timing_score)
        recent.append(raw)
        score = float(np.median(recent))
        # Rate agreement is real evidence from the first window; only the timing comparison waits for
        # this patient's baseline, so a learning bed with agreeing rates is checked, not "unknown".
        extra = dict(**rates, path='live_rate_and_pat', pat_ms=pat, baseline_pat_ms=usual,
                     baseline_samples=len(baseline), baseline_warming=usual is None, eligible=True,
                     raw_score=raw, persistence_windows=len(recent))
        # Admit only non-overlapping, mutually consistent observations; anomalies cannot train themselves away.
        start = window.get('window_start', 0)
        if (getattr(state,'baseline_admission_allowed',True) and pat is not None and
                mismatch < .2 and timing_score < .2 and start >= self.seen.get(bed, -10000)+10000):
            baseline.append(pat)
            self.seen[bed] = start
        if score < .5:
            reason = 'Heartbeat and pulse agree' + ('; learning this patient’s pulse timing' if usual is None else '')
        elif timing_score >= .5:
            reason = f"Pulse arrives {pat:.0f} ms after the heartbeat; this patient's usual is {usual:.0f} ms"
        elif mismatch >= .5:
            reason = f"ECG rate {ecg['rate']:.0f} bpm differs from pulse rate {ppg['rate']:.0f} bpm"
        else:
            reason = 'Heartbeat and pulse agree' + ('; learning this patient’s pulse timing' if usual is None else '')
        return result(score, reason, **extra)

    evaluate = __call__


class PressureDrift:
    """Arterial line vs cuff: is the line moving away from this patient's usual gap?

    The usual gap is learned only from the early cuff pairs (cuffs within EARLY_MS of the bed's
    first frame, at most EARLY_PAIRS, each plausible and consistent). A drifting line must not
    teach itself a new normal, so the baseline never updates after that. With no early pair the
    clinical prior applies: a zeroed line and a cuff agree on mean pressure (gap 0 mmHg).
    """
    EARLY_MS = 300000       # cuffs in the first 5 minutes on this bed may define its usual gap
    EARLY_PAIRS = 3
    PLAUSIBLE_MMHG = 25.    # a larger early gap is not a usable "normal" (damped/unzeroed line)
    CONSISTENT_MMHG = 5.    # early pairs must agree with each other
    PRIOR_GAP_MMHG = 0.
    SCALE_MMHG = 15.        # plain score = deviation / 15
    MARGIN_MMHG = 6.        # a growing deviation past this margin is drift (score >= .8)
    GROWTH_MMHG = 2.        # "growing": at least this much further from usual than the last cuff
    CUFF_STABLE_MMHG = 10.  # the cuff itself must stay roughly level (both falling is not drift)
    CLEAR_MMHG = 3.         # back within this of 0 or of the usual gap = re-zeroed

    def __init__(self):
        self.baselines = {}
        self.seen = {}
        self.current = {}
        self.first_ts = {}
        self.last_pair = {}
        self.drifting = {}

    def reset(self):
        for memory in (self.baselines, self.seen, self.current, self.first_ts, self.last_pair, self.drifting):
            memory.clear()

    def _usual(self, bed, cuff_ts):
        baseline = self.baselines.get(bed, ())
        early_open = cuff_ts <= self.first_ts[bed]+self.EARLY_MS and len(baseline) < self.EARLY_PAIRS
        if len(baseline) >= 2 or (baseline and not early_open):
            return float(np.median(baseline)), 'early_pairs'
        if not baseline and not early_open:
            return self.PRIOR_GAP_MMHG, 'clinical_prior'
        return None, 'learning'

    def _score(self, bed, gap, usual, cuff_map):
        deviation = gap-usual
        score = min(1., abs(deviation)/self.SCALE_MMHG)
        previous = self.last_pair.get(bed)
        self.last_pair[bed] = (deviation, cuff_map)
        sign = 1 if deviation > 0 else -1
        if previous is not None and abs(deviation) >= self.MARGIN_MMHG:
            prev_dev, prev_map = previous
            growing = (prev_dev*deviation >= 0 and abs(deviation) >= abs(prev_dev)+self.GROWTH_MMHG
                       and abs(cuff_map-prev_map) <= self.CUFF_STABLE_MMHG)
            if growing: self.drifting[bed] = sign
        if self.drifting.get(bed) == sign and abs(deviation) >= self.MARGIN_MMHG:
            # Gap kept growing past a clear margin and is still out there: drift, not one noisy cuff.
            score = max(score, min(1., .8+(abs(deviation)-self.MARGIN_MMHG)/30.))
        else:
            self.drifting.pop(bed, None)
        if min(abs(gap-self.PRIOR_GAP_MMHG), abs(deviation)) <= self.CLEAR_MMHG:
            # Re-zeroed / re-levelled: line and cuff agree again, clear at once.
            self.drifting.pop(bed, None)
            score = min(score, min(abs(deviation), abs(gap))/self.SCALE_MMHG)
        return score, deviation

    def __call__(self, window, state, now_ms):
        bed = (window or {}).get('bed_id', getattr(state,'bed_id','unknown'))
        frames = [r['message'] for r in state.messages
                  if now_ms-300000 <= r['received_ms'] <= now_ms and not r.get('sequence_issue')]
        start = (window or {}).get('window_start', now_ms-10000)
        end = start+10000 if window and 'window_start' in window else now_ms+1
        # The early-pair learning period is anchored to the first time this bed is checked.
        self.first_ts.setdefault(bed, min((m['ts'] for m in frames), default=now_ms))
        has_abp = any(start <= m['ts'] < end and isinstance(m.get('abp'),list) and
                      any(v is not None for v in m['abp']) for m in frames)
        if not has_abp:
            return result(None, 'No arterial line in this window', not_applicable=True,
                          no_arterial_line=True, path='live_patient_gap')
        baseline = self.baselines.setdefault(bed, deque(maxlen=self.EARLY_PAIRS))
        for frame in sorted((f for f in frames if f.get('nibp')), key=lambda f: f['nibp'].get('ts', 0)):
            cuff = frame.get('nibp')
            if not cuff or cuff.get('map') is None or cuff['ts'] > now_ms or now_ms-cuff['ts'] > 300000:
                continue
            if cuff['ts'] <= self.seen.get(bed, -1): continue
            # A cuff may arrive later than its source instant; pair only with nearby arterial samples.
            arterial = [v for m in frames if abs(m['ts']-cuff['ts']) <= 10000
                        for v in (m.get('abp') or []) if v is not None and math.isfinite(v)]
            if not arterial: continue
            gap = float(np.mean(arterial)-cuff['map'])
            usual, source = self._usual(bed, cuff['ts'])
            if usual is None:
                score, deviation = 0., 0.
            else:
                score, deviation = self._score(bed, gap, usual, cuff['map'])
            self.current[bed] = dict(score=score, gap_mmhg=gap, baseline_gap_mmhg=usual, baseline_source=source,
                                     deviation_mmhg=abs(deviation), cuff_ts=cuff['ts'], cuff_map=cuff['map'],
                                     drift_growing=bed in self.drifting)
            # Only early, plausible, mutually consistent pairs define this patient's usual gap.
            early = (cuff['ts'] <= self.first_ts[bed]+self.EARLY_MS and len(baseline) < self.EARLY_PAIRS
                     and abs(gap) <= self.PLAUSIBLE_MMHG and
                     (not baseline or abs(gap-float(np.median(baseline))) <= self.CONSISTENT_MMHG))
            if getattr(state,'baseline_admission_allowed',True) and early:
                baseline.append(gap)
            self.seen[bed] = cuff['ts']
        current = self.current.get(bed)
        if current is None:
            return result(None, 'Arterial line present; waiting for a paired cuff reading', eligible=False, not_applicable=True,
                          baseline_samples=len(baseline), path='live_patient_gap')
        if now_ms-current['cuff_ts'] > 300000:
            return result(None, 'Cuff reading is too old for a pressure comparison', eligible=False, not_applicable=True,
                          baseline_samples=len(baseline), path='live_patient_gap')
        usual = current['baseline_gap_mmhg']
        gap = current['gap_mmhg']
        if usual is None:
            reason = 'Learning this patient’s usual arterial-line/cuff gap'
        elif current['drift_growing'] and current['score'] >= .8:
            reason = (f"Line/cuff gap {gap:+.0f} mmHg vs usual {usual:+.0f} and growing; "
                      "re-level and re-zero the transducer")
        else:
            reason = (f"Line/cuff gap {gap:.0f} mmHg; this patient's usual is {usual:.0f} mmHg"
                      + (' (no early cuff: line and cuff should agree)' if current['baseline_source'] == 'clinical_prior' else ''))
        return result(current['score'], reason, **{k:v for k,v in current.items() if k!='score'},
                      baseline_samples=len(baseline), baseline_warming=usual is None, eligible=usual is not None,
                      # No cuff baseline yet = no drift evidence either way; it must not block NORMAL.
                      not_applicable=usual is None, path='live_patient_gap')

    evaluate = __call__


class NetworkAttack:
    @staticmethod
    def features(records):
        arrivals = np.array([r.get('received_mono_ms',r['received_ms']) for r in records],dtype=float)/1000
        iat = np.maximum(np.diff(arrivals),0)
        sizes = [r['payload_bytes'] for r in records]
        drifts = [abs(r['received_ms']-r['message']['ts'])/1000 for r in records]
        seqs = np.array([r['message']['seq'] for r in records],dtype=np.int64)
        delta = np.diff(seqs)
        return dict(msg_rate=len(records)/10., inter_arrival_mean=float(np.mean(iat)) if len(iat) else 0.,
                    inter_arrival_std=float(np.std(iat)) if len(iat) else 0.,
                    inter_arrival_min=float(np.min(iat)) if len(iat) else 0.,
                    inter_arrival_max=float(np.max(iat)) if len(iat) else 0.,
                    seq_gap_count=float(np.sum((delta>1)|(delta<0))), seq_dup_count=float(np.sum(delta==0)),
                    payload_bytes_mean=float(np.mean(sizes)) if sizes else 0.,
                    payload_bytes_std=float(np.std(sizes)) if sizes else 0.,
                    timestamp_drift_mean=float(np.mean(drifts)) if drifts else 0.,
                    timestamp_drift_max=float(np.max(drifts)) if drifts else 0.)

    def __call__(self, window, state, now_ms):
        recent = [r for r in state.messages if now_ms-10000 <= r['received_ms'] < now_ms]
        features = self.features(recent)
        senders = {r['sender_id'] for r in recent if r.get('sender_id') is not None}
        network = state.network
        source = None
        if network and now_ms-10000 <= network['window_start'] and network['window_start']+network['window_s']*1000 <= now_ms:
            source = network
        device = (state.last_message or window or {}).get('device_id')
        if source is not None and device is not None and source['device_id'] != device:
            source = None
        sender_count = max(len(senders), int((source or {}).get('senders') or 0))
        rate = max(features['msg_rate'], (source or {}).get('msgs_per_s') or 0.)
        repeats = max(features['seq_dup_count'], (source or {}).get('seq_repeats') or 0.)
        score = .95 if rate > 5 else 0.
        if repeats >= 2: score=max(score,.9)
        if sender_count > 1: score=max(score,.6)
        extra = dict(path='received_rules', features=features, senders=sender_count,
                     sender_identity_available=bool(senders) or (source is not None and source.get('senders') is not None),
                     source_window_s=10, observed_messages=len(recent))
        if source is not None:
            extra.update(path='received_and_topic7_rules' if recent else 'topic7_rules',
                         topic7_window_start=source['window_start'], topic7_window_s=source['window_s'],
                         topic7_features={k:v for k,v in source.items() if k not in
                                          {'v','type','device_id','window_start','window_s','received_ms'}})
        if not recent and not (source is not None and (rate > 0 or repeats > 0 or sender_count > 1)):
            return result(None, 'No recent packets; silence alone is not a network attack', eligible=False, **extra)
        reason = ('Message flood at '+str(round(rate,1))+' messages/s' if rate>5 else
                  'Repeated or regressed packet sequences' if repeats>=2 else
                  'Second sender observed; bedside confirmation needed' if sender_count>1 else
                  'No network attack evidence in received traffic')
        return result(score,reason,**extra)

    evaluate = __call__
