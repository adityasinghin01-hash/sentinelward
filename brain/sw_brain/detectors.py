"""Live heuristics: suspiciousness in [0,1]; advisory and uncalibrated."""
from __future__ import annotations
from collections import deque
from copy import deepcopy
import numpy as np
from scipy.signal import butter, find_peaks, peak_widths, sosfiltfilt

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


FS=125
# QRS band (Pan & Tompkins 1985): 5-15 Hz keeps the sharp QRS and drops P/T waves and baseline wander.
_QRS_SOS=butter(2,[5,15],btype='bandpass',fs=FS,output='sos')
# Pulse band: 0.5-8 Hz keeps the pulse upstroke, drops baseline drift and the dicrotic-notch ripple.
_PPG_SOS=butter(2,[.5,8],btype='bandpass',fs=FS,output='sos')


def ecg_beats(x):
    """R-peak sample indices from a 125 Hz single-lead ECG (no NaNs).

    Band-pass 5-15 Hz -> derivative -> square -> 120 ms moving integration, then peaks at least
    250 ms apart (max 240 bpm) above an adaptive threshold. Each beat is refined to the largest
    |band-passed| sample within +-60 ms so T waves and noise are not counted as extra beats.
    """
    band=sosfiltfilt(_QRS_SOS,x)
    energy=np.convolve(np.gradient(band)**2,np.ones(15)/15,mode='same')
    if not np.any(energy>0): return np.array([],dtype=int),band
    height=.30*float(np.percentile(energy,98))
    candidates,_=find_peaks(energy,height=height,distance=int(.25*FS))
    half=int(.06*FS); beats=[]
    for c in candidates:
        lo,hi=max(0,c-half),min(len(band),c+half+1)
        r=lo+int(np.argmax(np.abs(band[lo:hi])))
        if not beats or r-beats[-1]>=int(.25*FS): beats.append(r)
    return np.array(beats,dtype=int),band


def rhythm_rate(band):
    """Beats per minute from the dominant repeat interval (autocorrelation, 30-200 bpm), or None.

    Robust to dicrotic notches, small extra peaks and amplitude changes that break peak counting.
    """
    x=band-np.mean(band)
    if not np.any(x): return None
    ac=np.correlate(x,x,mode='full')[len(x)-1:]
    ac=ac/ac[0]
    lo,hi=int(FS*60/200),int(FS*60/30)
    seg=ac[lo:hi]
    peaks,props=find_peaks(seg,height=.3)
    if not len(peaks): return None
    # The first strong repeat is the beat interval (later ones are its multiples).
    strongest=float(np.max(props['peak_heights']))
    lag=int(peaks[np.argmax(props['peak_heights']>=.5*strongest)])+lo
    # If alternate beats look alike, the strongest repeat can be every second beat: prefer a clear
    # repeat at half that interval (still within 30-200 bpm).
    half=lag//2
    if half>=lo:
        w=max(2,half//10)
        near=ac[max(lo,half-w):half+w+1]
        if len(near) and float(np.max(near))>=.3:
            lag=max(lo,half-w)+int(np.argmax(near))
    return float(60*FS/lag)


def pulse_metrics(window,channel='ecg'):
    """Rate, beat times and approximate QRS width from observed samples only."""
    x=waveform(window,channel)
    if len(x)<250 or np.mean(np.isfinite(x))<.95: return None
    x=np.nan_to_num(x,nan=float(np.nanmedian(x)))
    x=x-np.median(x)
    if channel=='ecg':
        peaks,band=ecg_beats(x)
        widths=peak_widths(np.abs(band),peaks,rel_height=.5)[0] if len(peaks) else np.array([])
        widths=widths[widths>0]
    else:
        band=sosfiltfilt(_PPG_SOS,x)
        spread=float(np.percentile(band,95)-np.percentile(band,5))  # robust to single spikes
        peaks,properties=find_peaks(band,distance=int(.33*FS),prominence=max(1e-6,.35*spread),width=1)
        widths=properties['widths']
    if len(peaks)<2: return {'rate':0.,'peaks':peaks,'regularity':None,'qrs_ms':None}
    intervals=np.diff(peaks)/FS
    rate=float(60/np.median(intervals))
    if channel!='ecg':
        rhythm=rhythm_rate(band)
        if rhythm is not None: rate=rhythm  # peaks still give pulse timing; the rhythm gives the rate
    return {'rate':rate,'peaks':peaks,'regularity':float(np.std(intervals)/np.mean(intervals)),
            'qrs_ms':float(np.median(widths)*1000/FS) if len(widths) else None}

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
                return result(p,evidence,path='gbt_prealarm',model_version=gbt.get('model_version',MODEL_VERSION),alarm_code=code,positive=positive,threshold=gbt['threshold'],features=x,alarm_preserved=True)
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


LOW_CUFF_MAP=65        # cuff MAP below this is low
LINE_AGREE_MAP=70      # the arterial line agrees within tolerance if its 10 s mean is below this
LINE_RECOVERED_MS=60000  # release only after the line mean stays >= LINE_AGREE_MAP this long
CUFF_FRESH_MS=300000


def confirmed_low_pressure(state,now_ms):
    """Independent cuff/arterial safety check, held as one episode (even without an alarm).

    Confirm when a fresh cuff MAP is < 65 and the arterial line's 10 s mean agrees (< 70).
    Hold until the line mean is >= 70 for 60 s, or a new cuff reads >= 65. A line mean that
    hovers around 65 between two cuffs never drops the emergency. Updated incrementally per bed.
    """
    memo=getattr(state,'_low_pressure',None)
    if memo is None:
        memo={'last_ts':None,'cuff':None,'held':False,'recovering':None,'line':deque()}
        setattr(state,'_low_pressure',memo)
    frames=[]
    for record in reversed(state.messages):
        message=record['message']; ts=message.get('ts',now_ms)
        if memo['last_ts'] is not None and ts<=memo['last_ts']: break
        if record.get('sequence_issue') or record.get('received_ms',ts)>now_ms: continue
        frames.append(message)
    last=state.last_message
    if last is not None and not any(m is last for m in frames) and (memo['last_ts'] is None or last.get('ts',now_ms)>memo['last_ts']):
        frames.append(last)
    for message in sorted(frames,key=lambda m:m.get('ts',now_ms)):
        ts=message.get('ts',now_ms)
        if memo['last_ts'] is not None and ts<=memo['last_ts']: continue
        memo['last_ts']=ts
        cuff=message.get('nibp')
        if cuff and cuff.get('map') is not None and cuff.get('ts',ts)<=ts and (memo['cuff'] is None or cuff['ts']>memo['cuff']['ts']):
            memo['cuff']={'ts':cuff['ts'],'map':cuff['map']}
            if cuff['map']>=LOW_CUFF_MAP: memo['held']=False; memo['recovering']=None  # a new normal cuff releases
        observed=[v for v in (message.get('abp') or []) if v is not None and np.isfinite(v)]
        line=memo['line']
        if observed: line.append((ts,float(np.sum(observed)),len(observed)))
        while line and line[0][0]<=ts-10000: line.popleft()
        mean=sum(s for _,s,_ in line)/sum(n for _,_,n in line) if line and observed else None
        cuff=memo['cuff']
        if not memo['held']:
            if (mean is not None and mean<LINE_AGREE_MAP and cuff is not None and cuff['map']<LOW_CUFF_MAP
                    and 0<=ts-cuff['ts']<=CUFF_FRESH_MS):
                memo['held']=True; memo['recovering']=None
        elif mean is not None:
            if mean>=LINE_AGREE_MAP:
                memo['recovering']=ts if memo['recovering'] is None else memo['recovering']
                if ts-memo['recovering']>=LINE_RECOVERED_MS: memo['held']=False; memo['recovering']=None
            else: memo['recovering']=None
        if observed: memo['line_ts']=ts
    # No arterial sample at all for as long as a cuff stays fresh: nothing left to hold on.
    if memo['held'] and now_ms-memo.get('line_ts',now_ms)>CUFF_FRESH_MS: return False
    return bool(memo['held'])

class ReplayDetector:
    def __init__(self): self.history={}; self.pending_sender_checks={}
    def reset(self): self.history.clear(); self.pending_sender_checks.clear()
    @staticmethod
    def network_source(state,now_ms):
        # MQTT receipts have no publisher identity. Topic 7 supplies only a
        # device-level count, never identities to attach to individual frames.
        source=state.network
        device=(state.last_message or {}).get('device_id')
        # Both services publish/score on a five-second grid. The previous
        # completed feature window must survive scheduler jitter at this tick;
        # comparing its start with wall time drops it just 1 ms after the grid.
        end=now_ms//5000*5000
        if (source and device is not None and source['device_id']==device and
                source.get('received_ms',now_ms)<=now_ms and
                end-10000<=source['window_start'] and
                source['window_start']+source['window_s']*1000<=now_ms):
            return source
        return None

    @staticmethod
    def transport(state,now_ms,*,recent_start=None):
        # Compare whole envelopes, including alarms/numerics/optional leads. The
        # first arriving publisher need not be the real monitor. A matching frame
        # from either connection proves a copy; conflicting claims remain strong.
        records=[r for r in state.messages if now_ms-45000<=r['received_ms']<=now_ms]
        cutoff=now_ms-10000 if recent_start is None else recent_start
        recent=[r for r in records if cutoff<=r['received_ms']<=now_ms]
        by_seq={}; by_ts={}; copies=set(); conflicts=set()
        for r in records:
            m=r['message']; seq=m['seq']; ts=m['ts']
            for previous in (by_seq.get(seq),by_ts.get(ts)):
                if previous is None: continue
                if previous['message']==m:
                    if not previous.get('sequence_issue') or not r.get('sequence_issue'):
                        copies.update((id(previous),id(r)))
                else:
                    conflicts.update((id(previous),id(r)))
            by_seq.setdefault(seq,r); by_ts.setdefault(ts,r)
        issues=[r for r in recent if r.get('sequence_issue')]
        # A current identical copy is transport abuse. Old or unverified sequence
        # regressions still count as replay, even without authenticated identity.
        unexplained=[r for r in issues if id(r) not in copies or abs(r['received_ms']-r['message']['ts'])>3000]
        conflict=any(id(r) in conflicts for r in recent)
        senders={r['sender_id'] for r in recent if r.get('sender_id') is not None}
        source=ReplayDetector.network_source(state,now_ms)
        sender_count=max(len(senders),int((source or {}).get('senders') or 0))
        # Keep a bounded witness of a flood, then require the SAME connection to
        # continue at monitor pace in at least two completed seconds. A flood's
        # many copies of one sequence do not also count as paced impersonation.
        buckets={}
        for r in records:
            sender=r.get('sender_id')
            if sender is not None:
                buckets.setdefault(sender,{}).setdefault(r['received_ms']//1000,[]).append(r)
        combined=False
        for seconds in buckets.values():
            floods=[sec for sec,rows in seconds.items() if len(rows)>5]
            if not floods: continue
            last_flood=max(floods)
            paced=[sec for sec,rows in seconds.items() if last_flood<sec<now_ms//1000 and
                   sec*1000>=now_ms-10000 and 1<=len(rows)<=2 and
                   any(id(r) in copies and abs(r['received_ms']-r['message']['ts'])<=3000 for r in rows)]
            if len(paced)>=2: combined=True
        strong=conflict or bool(unexplained) or combined
        established=next((r.get('sender_id') for r in state.messages if
                          r['received_ms']<now_ms-10000 and not r.get('sequence_issue') and
                          r.get('sender_id') is not None),None)
        unverified_sender=any(r.get('sender_id')!=established and id(r) not in copies for r in recent)
        # Without IDs, identical complete envelopes still prove copies. They do
        # not prove WHO sent either copy. Keep the identity-based check when it
        # is actually available; a newly accepted unknown sender is unverified.
        anonymous=not senders and any(not r.get('sequence_issue') and
                                     r['received_ms']<now_ms-10000 for r in state.messages)
        copy_only=(bool(issues) and (established is not None or anonymous) and not conflict and not unexplained and
                   not unverified_sender and all(id(r) in copies for r in issues))
        return dict(recent=recent,sequence_events=len(issues),senders=sender_count,
                    sender_identity_available=bool(senders),
                    sender_count_available=bool(senders) or (source is not None and source.get('senders') is not None),
                    sender_count_window_start=source['window_start'] if source is not None else None,
                    content_conflict=conflict,
                    unexplained_sequence=bool(unexplained),flood_and_paced_sender=combined,
                    duplicate_only=copy_only,independent_evidence=strong)

    def evaluate(self,window,state,now_ms):
        extra=self.transport(state,now_ms)
        recent=extra.pop('recent')
        metadata_score=.98 if extra['independent_evidence'] else (.6 if extra['senders']>1 else 0.)
        extra.update(eligible=bool(recent),path='live_fingerprint_and_transport')
        # A brief paced impersonation requests a hand-check. Do not silently
        # clear that doubt when packets age out, nor create a nurse task for a
        # flood that belongs to IT. New traffic after a check reopens the doubt.
        bed=state.bed_id
        if .5<=metadata_score<.8 and recent and len(recent)<=50:
            # Use the time of the observed sender witness, not later ordinary
            # receipts. A delayed old window must not reopen a completed check.
            witness=extra['sender_count_window_start']
            observed=witness+5000-1 if witness is not None else max(r['received_ms'] for r in recent)
            if observed>getattr(state,'patient_ok_ts',-1):
                self.pending_sender_checks[bed]=max(self.pending_sender_checks.get(bed,-1),observed)
        pending=self.pending_sender_checks.get(bed)
        if pending is not None and pending<=getattr(state,'patient_ok_ts',-1)<=now_ms:
            self.pending_sender_checks.pop(bed,None); pending=None
        if pending is not None:
            metadata_score=max(metadata_score,.6)
            extra.update(eligible=True,pending_sender_check=True)
        reason=('Conflicting frame content for the same sequence or timestamp' if extra['content_conflict'] else
                'Old or unverified regressed sequence' if extra['unexplained_sequence'] else
                'Flood followed by paced impersonation from the same sender' if extra['flood_and_paced_sender'] else
                'Multiple publishers observed; bedside confirmation pending' if pending is not None else
                'Multiple publishers observed on this bed' if extra['senders']>1 else
                'No replay evidence in available bed history')
        if not window:
            return result(metadata_score,reason,**extra)
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
        if replay:
            reason='Near-identical waveform seen earlier on this bed'
            extra['duplicate_only']=False
        return result(value,reason,**extra)

class NetworkAttack:
    """M5 keeps the extractor rules; verified live copies are weak at normal pace."""
    @staticmethod
    def features(records):
        from .extended import NetworkAttack as ReceiptNetworkAttack
        return ReceiptNetworkAttack.features(records)

    def evaluate(self,window,state,now_ms):
        from .extended import NetworkAttack as ReceiptNetworkAttack
        value=ReceiptNetworkAttack().evaluate(window,state,now_ms)
        transport=ReplayDetector.transport(state,now_ms)
        # Topic-7 repeats of the same verified copies are not independent evidence.
        # Preserve excess repeats, floods, conflicts, old and unverified replays.
        topic=value['extra'].get('topic7_features',{})
        if (transport['duplicate_only'] and value['score'] is not None and
                value['extra']['features']['msg_rate']<=5 and
                (topic.get('msgs_per_s') or 0)<=5):
            verified=transport['sequence_events']
            start=value['extra'].get('topic7_window_start')
            if start is not None:
                # Compare extractor repeats with copies verified in THAT
                # completed interval. A late tick's moving look-back can lose
                # its first copy while the extractor still reports all five.
                end=start+value['extra']['topic7_window_s']*1000
                witness=ReplayDetector.transport(state,end-1,recent_start=start)
                verified=witness['sequence_events'] if witness['duplicate_only'] else 0
            if (topic.get('seq_repeats') or 0)<=verified:
                value=result(.6 if value['extra']['senders']>1 else 0.,
                             'Identical live copies; second sender needs bedside confirmation' if value['extra']['senders']>1 else
                             'Identical live packet copies; no changed data',**value['extra'])
        return value

    __call__=evaluate

class DetectorSuite:
    def __init__(self,m2_model=None):
        from .extended import BodyMismatch,PressureDrift
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
