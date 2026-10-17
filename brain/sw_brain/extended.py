"""Patient-specific live body/pressure checks and receipt-based network witness."""
from __future__ import annotations

from collections import deque
import math
import numpy as np

from .detectors import pulse_metrics, result


class BodyMismatch:
    def __init__(self):
        self.baselines = {}
        self.seen = {}

    def reset(self):
        self.baselines.clear()
        self.seen.clear()

    def __call__(self, window, state, now_ms):
        if not window:
            return result(0, 'Waiting for ECG and pulse window', eligible=False, path='live_rate_and_pat')
        ecg, ppg = pulse_metrics(window), pulse_metrics(window, 'ppg')
        if ecg is None or ppg is None:
            return result(0, 'Not enough observed ECG and pulse samples', eligible=False, path='live_rate_and_pat')
        rates = {'ecg_rate_bpm':ecg['rate'], 'ppg_rate_bpm':ppg['rate']}
        if (ecg['rate'] < 20) != (ppg['rate'] < 20):
            return result(.99, 'Heartbeat and pulse disagree: one signal has no usable beats', **rates, path='live_rate_and_pat')
        mismatch = min(1., abs(ecg['rate']-ppg['rate']) / max(20., .25 * max(ecg['rate'],ppg['rate'])))
        pats = []
        for beat in ecg['peaks']:
            after = (ppg['peaks'] - beat) * 8
            after = after[(after >= 80) & (after <= 700)]
            if len(after): pats.append(float(after[0]))
        bed = window['bed_id']
        baseline = self.baselines.setdefault(bed, deque(maxlen=60))
        usual = float(np.median(baseline)) if len(baseline) >= 3 else None
        pat = float(np.median(pats)) if len(pats) >= 3 else None
        timing_score = min(1., abs(pat-usual)/200) if pat is not None and usual is not None else 0.
        score = max(mismatch, timing_score)
        extra = dict(**rates, path='live_rate_and_pat', pat_ms=pat, baseline_pat_ms=usual,
                     baseline_samples=len(baseline), baseline_warming=usual is None, eligible=usual is not None or score>=.5)
        # Admit only non-overlapping, mutually consistent observations; anomalies cannot train themselves away.
        start = window.get('window_start', 0)
        if (getattr(state,'baseline_admission_allowed',True) and pat is not None and
                mismatch < .2 and timing_score < .2 and start >= self.seen.get(bed, -10000)+10000):
            baseline.append(pat)
            self.seen[bed] = start
        if timing_score >= .5:
            reason = f"Pulse arrives {pat:.0f} ms after the heartbeat; this patient's usual is {usual:.0f} ms"
        elif mismatch >= .5:
            reason = f"ECG rate {ecg['rate']:.0f} bpm differs from pulse rate {ppg['rate']:.0f} bpm"
        else:
            reason = 'Heartbeat and pulse agree' + ('; learning this patient’s pulse timing' if usual is None else '')
        return result(score, reason, **extra)

    evaluate = __call__


class PressureDrift:
    def __init__(self):
        self.baselines = {}
        self.seen = {}
        self.current = {}
        self.arterial_beds = set()

    def reset(self):
        self.baselines.clear()
        self.seen.clear()
        self.current.clear()
        self.arterial_beds.clear()

    def __call__(self, window, state, now_ms):
        bed = (window or {}).get('bed_id', getattr(state,'bed_id','unknown'))
        frames = [r['message'] for r in state.messages
                  if now_ms-300000 <= r['received_ms'] <= now_ms and not r.get('sequence_issue')]
        has_abp = any(isinstance(m.get('abp'),list) and any(v is not None for v in m['abp']) for m in frames)
        if has_abp: self.arterial_beds.add(bed)
        if not has_abp and bed not in self.arterial_beds:
            return result(None, 'No arterial line on this bed', no_arterial_line=True, path='live_patient_gap')
        baseline = self.baselines.setdefault(bed, deque(maxlen=30))
        for frame in frames:
            cuff = frame.get('nibp')
            if not cuff or cuff.get('map') is None or cuff['ts'] > now_ms or now_ms-cuff['ts'] > 300000:
                continue
            if cuff['ts'] <= self.seen.get(bed, -1): continue
            # A cuff may arrive later than its source instant; pair only with nearby arterial samples.
            arterial = [v for m in frames if abs(m['ts']-cuff['ts']) <= 10000
                        for v in (m.get('abp') or []) if v is not None and math.isfinite(v)]
            if not arterial: continue
            gap = float(np.mean(arterial)-cuff['map'])
            usual = float(np.median(baseline)) if len(baseline) >= 2 else None
            deviation = abs(gap-usual) if usual is not None else 0.
            score = min(1., deviation/15.)
            self.current[bed] = dict(score=score, gap_mmhg=gap, baseline_gap_mmhg=usual,
                                     deviation_mmhg=deviation, cuff_ts=cuff['ts'])
            # Require two distinct cuff observations, then reject changes >3 mmHg from normal.
            if getattr(state,'baseline_admission_allowed',True) and (usual is None or deviation <= 3):
                baseline.append(gap)
            self.seen[bed] = cuff['ts']
        current = self.current.get(bed)
        if current is None:
            return result(0., 'Arterial line present; waiting for a paired cuff reading', eligible=False,
                          baseline_samples=len(baseline), path='live_patient_gap')
        if now_ms-current['cuff_ts'] > 300000:
            return result(0., 'Cuff reading is too old for a pressure comparison', eligible=False,
                          baseline_samples=len(baseline), path='live_patient_gap')
        usual = current['baseline_gap_mmhg']
        reason = (f"Line/cuff gap {current['gap_mmhg']:.0f} mmHg; this patient's usual is {usual:.0f} mmHg"
                  if usual is not None else 'Learning this patient’s usual arterial-line/cuff gap')
        return result(current['score'], reason, **{k:v for k,v in current.items() if k!='score'},
                      baseline_samples=len(baseline), baseline_warming=usual is None, eligible=usual is not None,
                      path='live_patient_gap')

    evaluate = __call__


class NetworkAttack:
    def __init__(self, research=None):
        self.research = research

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
        sender_count = max(len(senders), int((source or {}).get('senders') or 0))
        score = .95 if features['msg_rate'] > 5 else 0.
        if features['seq_dup_count'] >= 2: score=max(score,.9)
        if sender_count > 1: score=max(score,.6)
        extra = dict(path='received_rules', features=features, senders=sender_count,
                     sender_identity_available=bool(senders) or source is not None,
                     source_window_s=10, observed_messages=len(recent))
        # Topic 7 provides the model's measured feature subset; complete only genuinely measured fields.
        if source is not None and self.research and len(recent)>=2:
            aliases = {'msgs_per_s':'msg_rate','iat_mean_ms':'inter_arrival_mean','iat_std_ms':'inter_arrival_std',
                       'payload_mean':'payload_bytes_mean','payload_std':'payload_bytes_std',
                       'seq_gaps':'seq_gap_count','seq_repeats':'seq_dup_count'}
            model_features = dict(features)
            complete = all(source.get(k) is not None for k in aliases)
            if complete:
                for key,dest in aliases.items(): model_features[dest]=source[key]/1000 if key.startswith('iat_') else source[key]
                output = self.research.m5(model_features, (window or {}).get('device_id',source['device_id']))
                extra['research'] = output
                extra['topic7_window_start'] = source['window_start']
                extra['topic7_window_s'] = source['window_s']
                extra['feature_spans'] = 'topic7 measured subset over 5s; IAT extrema and timestamp drift from own 10s receipts'
                if output.get('status')=='active':
                    score=max(score,output['score'])
                    extra.update(path='topic7_artifact',artifact_score=output['score'],features=model_features)
        if not recent:
            return result(0, 'No recent packets; silence alone is not a network attack', eligible=False, **extra)
        reason = ('Message flood at '+str(round(features['msg_rate'],1))+' messages/s' if features['msg_rate']>5 else
                  'Repeated or regressed packet sequences' if features['seq_dup_count']>=2 else
                  'Second sender observed; bedside confirmation needed' if sender_count>1 else
                  'No network attack evidence in received traffic')
        return result(score,reason,**extra)

    evaluate = __call__
