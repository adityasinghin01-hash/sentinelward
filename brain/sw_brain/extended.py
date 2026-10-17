"""Patient-specific live body/pressure checks and receipt-based network witness."""
from __future__ import annotations

from collections import deque
import math
import numpy as np

from .detectors import pulse_metrics, result


class BodyMismatch:
    """Compare reliable beat trains; never confuse an estimator alias with two bodies.

    Helpers shared with M2 remain untouched. Timing is a phase on the RR cycle,
    rather than the first pulse in an arbitrary 80--700 ms search interval.
    """
    PERSIST = 3

    def __init__(self):
        self.baselines = {}
        self.seen = {}
        self.recent = {}
        self.pulse_history = {}
        self.pulse_hold = {}
        self.cycles = {}
        self.observed = {}
        self.timing_track = {}

    def reset(self):
        self.baselines.clear()
        self.seen.clear()
        self.recent.clear()
        self.pulse_history.clear()
        self.pulse_hold.clear()
        self.cycles.clear()
        self.observed.clear()
        self.timing_track.clear()

    def _pulse_repeats(self, window, bed):
        # Search exact observed pulse subsequences at sample resolution. Reusing a
        # pulse at the same time is normal overlap; repeating BOTH channels belongs
        # to M4. Require three distinct non-flat pulse seconds so periodic signals cannot
        # manufacture source timestamps. Never infer times for unmatched samples.
        history = self.pulse_history.setdefault(bed, deque(maxlen=12))
        start = window.get('window_start', 0)
        pulse = np.asarray(window['ppg'], dtype=float).tobytes()
        heart = np.asarray(window['ecg'], dtype=float).tobytes()
        offsets = {}
        for i in range(0, len(pulse)-999, 1000):
            chunk = pulse[i:i+1000]
            x = np.frombuffer(chunk, dtype=float)
            if not np.all(np.isfinite(x)) or np.ptp(x) < 1e-4:
                continue
            matches = {}
            for old_start, old_pulse, old_heart in history:
                if not start-60000 <= old_start < start:
                    continue
                pos = old_pulse.find(chunk)
                while pos >= 0:
                    if pos % 8 == 0:
                        matches[old_start+pos] = old_heart[pos:pos+1000]
                    pos = old_pulse.find(chunk, pos+8)
            at = start+i
            if at in matches:
                continue  # normal overlap is not evidence of a shifted source
            for previous, old_ecg in matches.items():
                if old_ecg != heart[i:i+1000]:
                    offsets.setdefault(at-previous, set()).add(chunk)
        repeats = max((len(v) for v in offsets.values()), default=0)
        if not history or history[-1][0] != start:
            history.append((start, pulse, heart))
        return repeats

    def __call__(self, window, state, now_ms):
        if not window:
            return result(None, 'Waiting for ECG and pulse window', eligible=False, path='live_rate_and_pat')
        ecg, ppg = pulse_metrics(window), pulse_metrics(window, 'ppg')
        if ecg is None or ppg is None:
            return result(None, 'Not enough observed ECG and pulse samples', eligible=False, path='live_rate_and_pat')
        bed = window['bed_id']
        recent = self.recent.setdefault(bed, deque([0., 0.], maxlen=self.PERSIST))
        baseline = self.baselines.setdefault(bed, deque(maxlen=60))
        usual = float(np.median(baseline)) if len(baseline) >= 3 else None
        start = window.get('window_start', 0)
        previous = self.observed.get(bed)
        if previous is not None and start-previous[0] > 15000:
            recent.clear()
            recent.extend([0., 0.])
        # Plausible rates cannot prove that a known source-time violation ended.
        # Only the existing bedside confirmation or reset clears that integrity
        # evidence; no inferred timestamps or automatic learning can erase it.
        if getattr(state, 'patient_ok_ts', -1) > self.pulse_hold.get(bed, float('inf')):
            self.pulse_hold.pop(bed, None)
            self.pulse_history.pop(bed, None)
            recent.clear()
            recent.extend([0., 0.])
        repeats = self._pulse_repeats(window, bed)
        if repeats >= 3:
            self.pulse_hold.setdefault(bed, now_ms)
        replay = bed in self.pulse_hold
        rates = {'ecg_rate_bpm': ecg['rate'], 'ppg_rate_bpm': ppg['rate']}
        if (len(ecg['peaks']) < 2) != (len(ppg['peaks']) < 2):
            recent.append(.99)
            self.observed[bed] = (start, .99)
            return result(.99, 'Heartbeat and pulse disagree: one signal has no usable beats', **rates, path='live_rate_and_pat')

        er, pr = ecg['rate'], ppg['rate']
        peak_rate = float(7500/np.median(np.diff(ppg['peaks']))) if len(ppg['peaks']) >= 2 else 0.
        monitor = (getattr(state, 'last_message', None) or {}).get('hr')
        monitor_ok = monitor is not None and np.isfinite(monitor) and monitor >= 20
        agrees = lambda a, b: a >= 20 and b >= 20 and abs(a-b) <= .1*max(a,b)
        alias = False
        # Autocorrelation sometimes chooses two beats while peak timing sees each one.
        # A harmonic alone is NOT clearance: an unrelated half-rate pulse must still fail.
        if agrees(peak_rate, er) and not agrees(pr, er):
            harmonic = agrees(2*pr, peak_rate) or agrees(pr, 2*peak_rate)
            if harmonic or (monitor_ok and agrees(er, monitor)):
                pr = peak_rate
                alias = True
        rates.update(ppg_rate_bpm=pr, ppg_rhythm_rate_bpm=ppg['rate'], ppg_peak_rate_bpm=peak_rate,
                     monitor_hr_bpm=monitor if monitor_ok else None, rate_alias=alias)
        mismatch = min(1., max(0., abs(er-pr)/max(20., er, pr)-.05)/.1)
        # Missed or spurious peaks in an aperiodic/noisy waveform are not a measured
        # physiological rate. Do not let that estimate train PAT or establish tampering.
        reliable = (ecg['regularity'] is not None and ppg['regularity'] is not None and
                    ecg['regularity'] <= .25 and ppg['regularity'] <= .25 and er >= 20 and pr >= 20)
        rr_ms = 60000/er if er >= 20 else None
        pats = []
        if rr_ms:
            for beat in ecg['peaks'][1:-1]:
                delays = (ppg['peaks']-beat)*8
                if len(delays):
                    nearest = float(delays[np.argmin(np.abs(delays))])
                    if abs(nearest) <= rr_ms/2:
                        pats.append(nearest)
        pat = float(np.median(pats)) if len(pats) >= 3 else None
        # During warmup, compare plausible physical arrivals across changing RR.
        # Pick the most stable plausible arrival, then keep that physical baseline:
        # historic +/-RR alternatives must not hide a real change in arrival time.
        tracks = self.cycles.setdefault(bed, [deque(maxlen=60) for _ in range(3)])
        candidates = [pat+k*rr_ms for k in (0,-1,1)] if pat is not None else []
        normals = [float(np.median(t)) if len(t) >= 3 else None for t in tracks]
        timing_score = 0.
        if candidates and all(v is not None for v in normals):
            if bed not in self.timing_track:
                plausible = [i for i,v in enumerate(normals) if -80 <= v <= 1000]
                self.timing_track[bed] = min(plausible or range(3),
                    key=lambda i: (float(np.std(tracks[i])), i))
            reference = self.timing_track[bed]
            usual = normals[reference]
            pat = min(candidates, key=lambda value: abs(value-usual))
            timing_score = min(1., max(0., abs(pat-usual)-60)/160)
        # Unreliable peak timing cannot support PAT evidence, but irregularity is
        # never clearance for a persistent measured rate disagreement.
        raw = max(mismatch, timing_score if reliable else 0.)
        jitter = float(np.median(np.abs(np.asarray(pats)-np.median(pats)))) if len(pats) >= 3 else None
        if replay:
            raw = .99
        if previous != (start, raw):
            recent.append(raw)
        self.observed[bed] = (start, raw)
        score = float(np.median(recent))
        extra = dict(**rates, path='live_rate_and_pat', pat_ms=pat, baseline_pat_ms=usual,
                     baseline_samples=len(baseline), baseline_warming=usual is None, eligible=True,
                     raw_score=raw, persistence_windows=len(recent), beats_reliable=reliable,
                     pulse_repeat_seconds=repeats, pulse_replay_since_ms=self.pulse_hold.get(bed), pat_jitter_ms=jitter)
        if not reliable and mismatch >= .5 and not alias and not replay:
            recent.clear()
            recent.extend([0., 0.])
            return result(None, 'Pulse beat timing is unreliable; body match is not established',
                          **{**extra, 'eligible':False}, unavailable_reason='unreliable_beat_estimates')
        start = window.get('window_start', 0)
        admission = getattr(state, 'baseline_admission_allowed', True)
        if admission and reliable and candidates and mismatch < .2 and timing_score < .2 and not replay and start >= self.seen.get(bed, -10000)+10000:
            for i, (track, normal) in enumerate(zip(tracks, normals)):
                if bed in self.timing_track and i != self.timing_track[bed]:
                    continue
                candidate = candidates[i] if normal is None else min(candidates, key=lambda value: abs(value-normal))
                if normal is None or abs(candidate-normal) < 100:
                    track.append(candidate if normal is None else normal+float(np.clip(candidate-normal,-20,20)))
            baseline.append(candidates[0])
            self.seen[bed] = start
        if replay:
            reason = 'Pulse repeated at a different time from ECG; bedside confirmation required'
        elif alias:
            reason = 'Pulse rate alias, rechecking heartbeat and pulse timing'
        elif not reliable and score < .5:
            reason = 'Beat timing is irregular; the observed heartbeat and pulse rates agree'
        elif score >= .5 and timing_score >= .5:
            reason = f"Pulse timing {pat:.0f} ms from ECG; this patient's usual is {usual:.0f} ms"
        elif score >= .5 and mismatch >= .5:
            reason = f'ECG rate {er:.0f} bpm differs from pulse rate {pr:.0f} bpm'
        else:
            reason = 'Heartbeat and pulse agree' + ('; learning this patient’s pulse timing' if usual is None else '')
        return result(score, reason, **extra)

    evaluate = __call__

class PressureDrift:
    def __init__(self):
        self.baselines = {}
        self.seen = {}
        self.current = {}

    def reset(self):
        self.baselines.clear()
        self.seen.clear()
        self.current.clear()

    def __call__(self, window, state, now_ms):
        bed = (window or {}).get('bed_id', getattr(state,'bed_id','unknown'))
        frames = [r['message'] for r in state.messages
                  if now_ms-300000 <= r['received_ms'] <= now_ms and not r.get('sequence_issue')]
        start = (window or {}).get('window_start', now_ms-10000)
        end = start+10000 if window and 'window_start' in window else now_ms+1
        has_abp = any(start <= m['ts'] < end and isinstance(m.get('abp'),list) and
                      any(v is not None for v in m['abp']) for m in frames)
        if not has_abp:
            return result(None, 'No arterial line in this window', not_applicable=True,
                          no_arterial_line=True, path='live_patient_gap')
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
            return result(None, 'Arterial line present; waiting for a paired cuff reading', eligible=False, not_applicable=True,
                          baseline_samples=len(baseline), path='live_patient_gap')
        if now_ms-current['cuff_ts'] > 300000:
            return result(None, 'Cuff reading is too old for a pressure comparison', eligible=False, not_applicable=True,
                          baseline_samples=len(baseline), path='live_patient_gap')
        usual = current['baseline_gap_mmhg']
        reason = (f"Line/cuff gap {current['gap_mmhg']:.0f} mmHg; this patient's usual is {usual:.0f} mmHg"
                  if usual is not None else 'Learning this patient’s usual arterial-line/cuff gap')
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
