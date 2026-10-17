"""Live heuristics: suspiciousness in [0,1]; advisory and uncalibrated."""
from __future__ import annotations
from collections import deque
from copy import deepcopy
import numpy as np
from scipy.signal import find_peaks

LABELS={'M1':'sensor_unusable','M2':'real_emergency','M3':'body_mismatch','M4':'replay','M5':'network_attack','M6':'drift'}


def result(score,reason,**extra):
    eligible=score is not None and extra.get('eligible',True)
    if not eligible:
        score=None
        extra.setdefault('unavailable_reason',reason[:120])
    return {'score':None if score is None else float(np.clip(score,0,1)), 'reason':reason[:120], 'extra':{**extra,'eligible':bool(eligible)}}


def waveform(window,channel):
    values=window.get(channel,[]) if window else []
    return np.array([np.nan if v is None else v for v in values],dtype=float)


def pulse_metrics(window,channel='ecg'):
    """Rate, beat times and approximate QRS width from observed samples only."""
    x=waveform(window,channel)
    if len(x)<250 or np.mean(np.isfinite(x))<.95: return None
    x=np.nan_to_num(x,nan=float(np.nanmedian(x)))
    x=x-np.median(x)
    if channel=='ecg':
        # Dominant polarity allows inverted single-lead ECG.
        if abs(np.min(x))>abs(np.max(x)): x=-x
        prominence=max(.08,float(np.ptp(x))*.3)
    else: prominence=max(1e-6,float(np.ptp(x))*.25)
    peaks,properties=find_peaks(x,distance=25 if channel=='ecg' else 30,prominence=prominence,width=1)
    if len(peaks)<2: return {'rate':0.,'peaks':peaks,'regularity':None,'qrs_ms':None}
    intervals=np.diff(peaks)/125
    return {'rate':float(60/np.median(intervals)),'peaks':peaks,'regularity':float(np.std(intervals)/np.mean(intervals)), 'qrs_ms':float(np.median(properties['widths'])*8)}

class QualityDetector:
    def evaluate(self,window,state,now_ms):
        if not window: return result(None,'Waiting for 10 seconds of ECG and pulse',eligible=False,unavailable_reason='window_unavailable')
        checks={}
        for channel in ('ecg','ppg'):
            x=waveform(window,channel); valid=np.isfinite(x); issues=[]; severity=0.
            missing=1-float(np.mean(valid))
            if missing>.05: severity=max(severity,min(1,missing*2+.5)); issues.append('missing samples')
            y=x[valid]
            if len(y):
                span=float(np.ptp(y)); limits=(-10,10) if channel=='ecg' else (-1000,100000)
                if span < (0.015 if channel=='ecg' else 1e-4): severity=1.; issues.append('flat or stuck line')
                if np.mean((y<limits[0])|(y>limits[1]))>.01: severity=1.; issues.append('implausible amplitude')
                # Long exact plateaus at the extreme indicate saturation.
                extreme=(y==np.min(y))|(y==np.max(y))
                clipped=float(np.mean(extreme))
                if span>0 and clipped>.2: severity=max(severity,.9); issues.append('clipping')
                if len(y)==len(x) and span>0:
                    power=np.abs(np.fft.rfft(y-np.mean(y)))**2; freq=np.fft.rfftfreq(len(y),1/125)
                    total=float(np.sum(power))+1e-12
                    mains=float(np.sum(power[((freq>=48)&(freq<=52))|((freq>=58)&(freq<=62))])/total)
                    hf=float(np.sum(power[freq>35])/total)
                    if mains>.25: severity=max(severity,.95); issues.append('powerline interference')
                    elif hf>.5: severity=max(severity,.85); issues.append('high frequency noise')
                    checks[channel]={'missing_fraction':missing,'span':span,'clipped_fraction':clipped,'powerline_fraction':mains,'noise_fraction':hf}
            else: severity=1.; issues.append('all samples missing')
            checks.setdefault(channel,{'missing_fraction':missing})
            checks[channel].update(score=severity,issues=issues)
        bad=max(checks,key=lambda key:checks[key]['score']); value=checks[bad]['score']
        reason=f"{bad.upper()}: {', '.join(checks[bad]['issues'])}" if value else 'ECG and pulse signals are usable'
        return result(value,reason,channel=bad if value else None,channels=checks,path='live_signal_quality')

class EmergencyDetector:
    def __init__(self,gbt=None):
        from .m2gbt import GbtM2
        self.gbt=GbtM2() if gbt is None else gbt
    def reset(self):
        if self.gbt: self.gbt.reset()
    def evaluate(self,window,state,now_ms):
        bed=getattr(state,'bed_id',(window or {}).get('bed_id'))
        code=state.last_alarm_code if state.alarm_until_ms>0 and state.alarm_until_ms>=now_ms else None
        alarms=(window or {}).get('monitor_alarms',[])
        if code is None and alarms and getattr(state,'patient_ok_ts',-1)<window.get('window_start',0):
            code=alarms[-1]['code']
        if code is None:
            return result(None,'No monitor alarm in or just before this window',not_applicable=True)
        # Primary: trees on the exact 10 s pre-alarm window they were trained on. Explains only.
        gbt={'status':'unavailable','extra':{'unavailable_reason':'no_full_prealarm_window'}}
        prealarm=getattr(state,'prealarm_window',None)
        if prealarm is not None and self.gbt:
            gbt=self.gbt.evaluate(prealarm,code)
            if gbt.get('status')=='active':
                positive=gbt['positive']; p=gbt['score']; x=gbt['extra']
                evidence=f"{p:.0%} likely real {code} (threshold {gbt['threshold']:.2f})"
                if x.get('ecg_hr_bpm') is not None: evidence+=f"; ECG {x['ecg_hr_bpm']:.0f} bpm"
                if x.get('pulse_hr_bpm') is not None: evidence+=f", pulse {x['pulse_hr_bpm']:.0f} bpm"
                if confirmed_low_pressure(state,now_ms):
                    positive=True; evidence='Low arterial pressure confirmed by cuff; '+evidence
                from .m2gbt import MODEL_VERSION
                return result(p,evidence,path='gbt_prealarm',model_version=MODEL_VERSION,alarm_code=code,positive=positive,threshold=gbt['threshold'],features=x,alarm_preserved=True)
        if not window: return result(None,'Waiting for ECG window; monitor alarms still take priority',eligible=False,unavailable_reason='window_unavailable',gbt=gbt)
        metrics=pulse_metrics(window)
        if metrics is None: return result(None,'Too few valid ECG samples; monitor alarm is preserved',eligible=False,unavailable_reason='ecg_missing',gbt=gbt)
        rate=metrics['rate']; width=metrics['qrs_ms']; regularity=metrics['regularity']
        if code=='ASYSTOLE': positive=rate<20; evidence='ECG has very few beats'
        elif code=='BRADY': positive=rate<40; evidence=f'ECG rate is {rate:.0f} bpm'
        elif code=='TACHY': positive=rate>140; evidence=f'ECG rate is {rate:.0f} bpm'
        elif code=='VTACH': positive=rate>100 and width is not None and width>=100 and regularity is not None and regularity<.25; evidence=f'ECG rate {rate:.0f} bpm; QRS {width or 0:.0f} ms'
        elif code=='VFIB': positive=regularity is not None and regularity>.35 and rate>100; evidence='ECG is fast and irregular'
        else:
            pulse=pulse_metrics(window,'ppg')
            positive=(rate<20 and pulse is not None and pulse['rate']<20) or rate>180
            evidence=f'ECG rate is {rate:.0f} bpm'
        if confirmed_low_pressure(state,now_ms):
            positive=True; evidence='Low arterial pressure confirmed by cuff'
        return result(.95 if positive else .05,evidence+(' supports '+code if code else ''),path='live_ecg_rule',alarm_code=code,rate_bpm=rate,qrs_width_ms=width,regularity=regularity,positive=positive,gbt=gbt)


def confirmed_low_pressure(state,now_ms):
    """Preserve the independent cuff/arterial safety check even without an alarm."""
    frame=state.last_message or {}; cuff=frame.get('nibp'); abp=frame.get('abp')
    if cuff is None:
        cuff=next((r['message']['nibp'] for r in reversed(state.messages) if r['message'].get('nibp') and not r.get('sequence_issue')),None)
    if cuff and cuff.get('map') is not None and 0<=now_ms-cuff['ts']<=300000 and cuff['map']<65:
        observed=[v for v in (abp or []) if v is not None]
        return bool(observed and float(np.mean(observed))<65)
    return False

class ReplayDetector:
    def __init__(self): self.history={}
    def reset(self): self.history.clear()
    def evaluate(self,window,state,now_ms):
        recent=[r for r in state.messages if now_ms-10000<=r['received_ms']<=now_ms]
        evidence=[r for r in recent if r.get('sequence_issue')]
        senders={r['sender_id'] for r in recent if r.get('sender_id') is not None}
        metadata_score=.98 if evidence else (.6 if len(senders)>1 else 0.)
        extra={'eligible':bool(recent),'path':'live_fingerprint_and_transport','sequence_events':len(evidence),'senders':len(senders),'sender_identity_available':bool(senders),'independent_evidence':bool(evidence or len(senders)>1)}
        if not window:
            return result(metadata_score,'Repeated or regressed sequence' if evidence else 'Waiting for a full waveform window',**extra)
        history=self.history.setdefault(state.bed_id,deque(maxlen=120))
        fingerprint=[]
        for channel in ('ecg','ppg'):
            x=waveform(window,channel)
            if np.mean(np.isfinite(x))<.95 or np.nanstd(x)<1e-8:
                return result(metadata_score,'Replay checked from sequence and sender; waveform unusable',**extra,unavailable_waveform=True)
            x=np.nan_to_num(x,nan=float(np.nanmedian(x)))
            fingerprint.append((x-np.mean(x))/np.std(x))
        fingerprint=np.stack(fingerprint)
        best=None; similarity=0.
        for previous,reference in history:
            if reference['window_start']+10000>window['window_start']: continue
            similarity_here=float(1-np.mean(np.abs(previous-fingerprint))/2)
            if similarity_here>similarity: similarity=similarity_here; best=reference
        replay=best is not None and similarity>=.995
        extra.update(fingerprint_similarity=similarity,reference_window_start=best['window_start'] if best else None,waveform_replay=replay,independent_evidence=extra['independent_evidence'] or replay)
        if getattr(state,'baseline_admission_allowed',True) and not replay and not metadata_score and not any(ref['window_start']==window['window_start'] for _,ref in history): history.append((fingerprint,window))
        value=max(metadata_score,.99 if replay else min(.3,max(0.,similarity*.2)))
        reason='Near-identical waveform seen earlier on this bed' if replay else ('Repeated or regressed sequence' if evidence else ('Second authenticated sender on this bed' if len(senders)>1 else 'No replay evidence in available bed history'))
        return result(value,reason,**extra)

class DetectorSuite:
    def __init__(self,m2_model=None):
        from .extended import BodyMismatch,NetworkAttack,PressureDrift
        self.detectors={'M1':QualityDetector(),'M2':EmergencyDetector(m2_model),'M3':BodyMismatch(),'M4':ReplayDetector(),'M5':NetworkAttack(),'M6':PressureDrift()}
    def reset(self):
        for detector in self.detectors.values():
            if hasattr(detector,'reset'): detector.reset()
    def evaluate(self,window,state,now_ms):
        values={}
        # Baselines only learn after current quality, clinical and transport checks.
        state.baseline_admission_allowed=False
        for i in (1,2,5,4,3,6):
            model=f'M{i}'
            if i==4:
                state.baseline_admission_allowed=all(values[m]['extra'].get('not_applicable',False) or (values[m]['score'] is not None and values[m]['score']<.5 and values[m]['extra'].get('eligible',False)) for m in ('M1','M2','M5')) and state.alarm_until_ms<now_ms and not state.patient_not_ok and not confirmed_low_pressure(state,now_ms)
            if i==3:
                state.baseline_admission_allowed=state.baseline_admission_allowed and values['M4']['score'] is not None and values['M4']['score']<.5
            if model in self.detectors:
                try: values[model]=self.detectors[model].evaluate(window,state,now_ms)
                except Exception as exc: values[model]=result(None,'Live detector unavailable',eligible=False,unavailable_reason=f'{type(exc).__name__}: {exc}')
            else: values[model]=result(None,'Detector is not enabled in this working step',unavailable_reason='step_2_pending')
        # A body mismatch discovered after fingerprint evaluation invalidates that reference.
        if window and values['M3']['score'] is not None and values['M3']['score']>=.5:
            history=self.detectors['M4'].history.get(state.bed_id)
            if history and history[-1][1]['window_start']==window['window_start']: history.pop()
        return {f'M{i}':values[f'M{i}'] for i in range(1,7)}
