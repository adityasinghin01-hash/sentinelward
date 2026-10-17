"""One-process service: receipts, strict windows, live detectors, retained verdicts."""
from __future__ import annotations
from collections import deque
from copy import deepcopy
from dataclasses import dataclass,field
import logging
from sw_common import make_score
from sw_common.topics import BEDSIDE_SUB, DEMO_CONTROL_TOPIC, NET_SUB, VITALS_SUB, score_topic, verdict_topic
from .io import decode,publish_checked
from .windows import VitalsWindowAssembler,assemble_window
from .detectors import DetectorSuite,LABELS,confirmed_low_pressure
from .decision import decide

log=logging.getLogger(__name__)

@dataclass
class BedState:
    bed_id: str
    messages: deque=field(default_factory=lambda:deque(maxlen=4096))
    windows: deque=field(default_factory=lambda:deque(maxlen=120))
    chunks: deque=field(default_factory=lambda:deque(maxlen=10))
    network: dict | None=None
    last_message: dict | None=None
    last_received_ms: int | None=None
    last_seq: int | None=None
    last_ts: int | None=None
    alarm_until_ms: int=0
    last_alarm_code: str | None=None
    alarm_ts: int | None=None
    patient_ok_ts: int=-1
    last_bedside_ts: int=-1
    patient_not_ok: bool=False
    prealarm_window: dict | None=None
    last_trusted_ts: int | None=None

class BrainService:
    def __init__(self,bus,*,suite=None):
        self.bus=bus; self.assembler=VitalsWindowAssembler(); self.suite=suite or DetectorSuite()
        self.beds={}; self.snapshots={}; self.last_trusted_snapshots={}; self.last_verdicts={}; self.controls=deque(maxlen=128)
        self._run_generation=0
        self.last_tick_ms=None
        self.invalid_incoming=0; self.invalid_outgoing=0
        self.last_control_ts=-1; self.run_started_ms=None; self.active_run_id=None
        for topic,qos in [(VITALS_SUB,0),(NET_SUB,1),(BEDSIDE_SUB,1),(DEMO_CONTROL_TOPIC,1)]: bus.subscribe(topic,self.receive,qos=qos)
    def reset(self):
        self._run_generation+=1
        # Old retained verdicts would show a bed that has not joined this run as UNSURE, or replay an old alarm to a fresh subscriber.
        stale=set(self.beds)|set(self.last_verdicts)|{f'B{i:02d}' for i in range(1,13)}
        clear=getattr(self.bus,'clear_retained',None)
        for bed in sorted(stale if clear else ()):
            try: clear(verdict_topic(bed))
            except Exception as exc: log.warning('Could not clear retained verdict for %s: %s',bed,exc)
        self.beds.clear(); self.assembler.reset(); self.suite.reset(); self.last_tick_ms=None
        self.last_verdicts.clear(); self.active_run_id=None; self.run_started_ms=None
    def receive(self,topic,payload,received_ms=None,sender_id=None,received_mono_ms=None):
        try: receipt=decode(topic,payload,received_ms,sender_id,received_mono_ms)
        except ValueError as exc:
            self.invalid_incoming+=1
            log.warning('Rejected message on %s: %s',topic,exc); return False
        message=receipt.data; kind=message['type']; now=receipt.received_ms
        if kind not in {'vitals','net_features','bedside_check','demo_control'}: return False
        if kind=='demo_control':
            if message['cmd']=='run' and self.active_run_id==message['run_id']: return False
            if message['ts']<self.last_control_ts: return False
            key=(message['cmd'],message['run_id'],message['ts'],message['start_at_s'])
            if key in self.controls: return False
            self.controls.append(key); self.last_control_ts=message['ts']
            self.reset()
            if message['cmd']=='run':
                self.active_run_id=message['run_id']; self.run_started_ms=message['ts']
            return True
        if self.run_started_ms is not None and (now<self.run_started_ms or (kind!='vitals' and message.get('ts',message.get('window_start',now))<self.run_started_ms)): return False
        if kind=='net_features':
            bed='B'+message['device_id'][4:]
            state=self.beds.setdefault(bed,BedState(bed))
            state.network={**message,'received_ms':now}
            return True
        bed=message['bed_id']; state=self.beds.setdefault(bed,BedState(bed))
        if kind=='bedside_check':
            if message['ts']<state.last_bedside_ts or (message['ts']==state.last_bedside_ts and state.patient_not_ok): return False
            state.last_bedside_ts=message['ts']
            if message['result']=='patient_ok':
                state.patient_ok_ts=message['ts']; state.alarm_until_ms=0; state.patient_not_ok=False; state.prealarm_window=None
            else: state.patient_not_ok=True
            return True
        # Safety: a valid monitor alarm is remembered even if replay detection rejects its frame.
        alarm=message['monitor_alarm']
        if alarm and message['ts']>state.patient_ok_ts:
            previous_alarm=(state.last_message or {}).get('monitor_alarm') or {}
            same_episode=(state.alarm_until_ms>=now and state.last_alarm_code==alarm['code'] and
                          (message['ts']==state.alarm_ts or
                           (previous_alarm.get('code')==alarm['code'] and state.last_ts is not None and
                            message['ts']==state.last_ts+1000 and message['seq']==state.last_seq+1)))
            state.alarm_until_ms=max(state.alarm_until_ms,message['ts']+40000,now+30000)
            if not same_episode:
                state.prealarm_window=None
                state.alarm_ts=message['ts']
                if len(state.chunks)==10 and state.chunks[0]['ts']==message['ts']-10000 and state.chunks[-1]['ts']==message['ts']-1000:
                    state.prealarm_window=self._window_from_chunks(state, list(state.chunks))
            state.last_alarm_code=alarm['code']
        sequence_issue=state.last_seq is not None and (message['seq']<=state.last_seq or message['ts']<=state.last_ts)
        record={'message':message,'received_ms':now,'payload_bytes':receipt.payload_bytes,'sender_id':sender_id,'sequence_issue':sequence_issue}
        if receipt.received_mono_ms is not None: record['received_mono_ms']=receipt.received_mono_ms
        state.messages.append(record)
        state.last_received_ms=now
        if sequence_issue: return False
        if state.last_seq is not None and (message['seq']!=state.last_seq+1 or message['ts']!=state.last_ts+1000): state.chunks.clear()
        try: window=self.assembler.ingest(message)
        except ValueError as exc: log.warning('Rejected window chunk: %s',exc); return False
        state.last_seq=message['seq']; state.last_ts=message['ts']; state.last_message=deepcopy(message)
        state.chunks.append(deepcopy(message)); self.snapshots[bed]=deepcopy(message)
        if window is not None: state.windows.append(window)
        return True
    def display_snapshot(self,bed):
        verdict=self.last_verdicts.get(bed,{})
        trusted=verdict.get('verdict')=='NORMAL'
        return deepcopy(self.snapshots.get(bed) if trusted else self.last_trusted_snapshots.get(bed,self.snapshots.get(bed)))
    @staticmethod
    def _window_from_chunks(state,chunks):
        data={'bed_id':state.bed_id,'device_id':chunks[0]['device_id'],'window_start':chunks[0]['ts'],'window_s':10,'sample_rate_hz':125,'monitor_alarms':[],'seq_first':chunks[0]['seq'],'seq_last':chunks[-1]['seq']}
        for channel in ('ecg','ppg'):
            data[channel]=[v for c in chunks for v in (c[channel] or [None]*125)]
            data[channel+'_valid']=[v is not None for v in data[channel]]
        # Arterial line only when present in some second; absent seconds stay missing.
        data['abp']=[v for c in chunks for v in (c.get('abp') or [None]*125)] if any(c.get('abp') for c in chunks) else None
        # doc 00 v1.3: optional second ECG lead; absent seconds stay missing, absent everywhere = None.
        data['ecg2']=[v for c in chunks for v in (c.get('ecg2') or [None]*125)] if any(c.get('ecg2') for c in chunks) else None
        data['ecg_leads']=next((list(c['ecg_leads']) for c in reversed(chunks) if c.get('ecg2') and c.get('ecg_leads')),None)
        return data
    def tick(self,now_ms):
        generation=self._run_generation
        # Caller uses epoch-aligned deadlines. Negative starts are avoided during initial epoch fixtures.
        end=(int(now_ms)//5000)*5000; start=max(0,end-10000); verdicts=[]
        for bed,state in sorted(self.beds.items()):
            if state.last_received_ms is None: continue
            offline=now_ms-state.last_received_ms>=3000
            window=next((w for w in reversed(state.windows) if w['window_start']==start),None)
            results=self.suite.evaluate(window,state,now_ms)
            for model,value in results.items():
                # Controls clear memory without stopping scoring. Discard work from an old run.
                if generation!=self._run_generation: return []
                envelope=make_score(bed_id=bed,model=model,model_version=value['extra'].get('model_version',model+'-live-2026-10-17'),window_start=start,window_s=10,score=value['score'],label=LABELS[model],reason=value['reason'][:120],extra={**value['extra'],'offline':offline})
                self._publish(score_topic(bed,model),envelope)
            if generation!=self._run_generation: return []
            alarm=now_ms<=state.alarm_until_ms and state.alarm_until_ms>0
            verdict=decide(bed,start,int(now_ms),results,alarm=alarm,offline=offline,last_trusted_ts=state.last_trusted_ts,patient_not_ok=state.patient_not_ok,confirmed_low_pressure=confirmed_low_pressure(state,now_ms))
            if generation!=self._run_generation: return []
            if verdict['verdict']=='NORMAL':
                state.last_trusted_ts=int(now_ms)
                self.last_trusted_snapshots[bed]=deepcopy(state.last_message)
            self.last_verdicts[bed]=verdict
            self._publish(verdict_topic(bed),verdict,retain=True)
            if generation!=self._run_generation: return []
            verdicts.append(verdict)
        self.last_tick_ms=end
        return verdicts

    def _publish(self,topic,message,retain=False):
        try: return publish_checked(self.bus,topic,message,qos=1,retain=retain)
        except ValueError as exc:
            self.invalid_outgoing+=1
            log.warning('Rejected outgoing message on %s: %s',topic,exc)
            return False
