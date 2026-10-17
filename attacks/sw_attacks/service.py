"""Single-threaded, absolute-clock scheduler with no catch-up flood bursts."""
from __future__ import annotations
from collections import OrderedDict,deque
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path

from sw_common.topics import DEMO_CONTROL_TOPIC,VITALS_SUB,vitals_topic
from sw_brain.io import decode,encode,publish_checked
from .events import EventLog
from .schedule import load_schedule
from .scenarios import SourceUnavailable,transform

log=logging.getLogger(__name__)

class AttackService:
    def __init__(self,bus,*,runs_dir=None,schedule_path=None,fixtures=None):
        self.bus=bus; self.runs_dir=Path(runs_dir or Path(__file__).resolve().parents[1]/'runs')
        self.schedule=load_schedule(schedule_path); self.history={}; self.latest={}; self.fixture_history={}
        self.own_hashes=OrderedDict(); self.running=False; self.origin_ms=None; self.start_ms=None
        self.states={}; self.event_log=None; self.last_control_ts=-1; self.controls=deque(maxlen=128)
        self.invalid_incoming=0; self.invalid_outgoing=0
        for topic,qos in [(VITALS_SUB,0),(DEMO_CONTROL_TOPIC,1)]: self.bus.subscribe(topic,self.receive,qos=qos)
        if fixtures is not None: self.load_fixtures(fixtures)
    def load_fixtures(self,path):
        """JSONL of original vitals or {'t_s': source-second, 'message': original vitals}."""
        with Path(path).open(encoding='utf-8') as stream:
            for index,row in enumerate(stream,1):
                if not row.strip(): continue
                item=json.loads(row)
                if isinstance(item,dict) and 'message' in item:
                    t_s=item.get('t_s')
                    if isinstance(t_s,bool) or not isinstance(t_s,int) or not 0<=t_s<1200: raise ValueError(f'Fixture line {index}: t_s must be an integer source second')
                    message=item['message']; topic=vitals_topic(message.get('bed_id'))
                    receipt=decode(topic,json.dumps(message))
                    self.fixture_history[(message['bed_id'],t_s)]=deepcopy(receipt.data)
                else:
                    topic=vitals_topic(item.get('bed_id')); receipt=decode(topic,json.dumps(item))
                    self._capture(receipt.data)
    @staticmethod
    def _digest(topic,message): return hashlib.sha256(encode(topic,message)).digest()
    # Margin on top of each replay's look-back (start_s - source_start_s) for late or seeked starts.
    HISTORY_MARGIN_S=60
    MASK_LOOKBACK_S=60  # flood_second_sender masks the patient with this bed's own frames from 60 s earlier
    def _history_lookback_ms(self,bed):
        """Replay and the B07 masking loop read history: keep their look-back plus a margin; other beds need just `latest`."""
        lookbacks=[s['start_s']-s['source_start_s'] for s in self.schedule if s['kind']=='replay' and s['bed_id']==bed]
        lookbacks+=[self.MASK_LOOKBACK_S for s in self.schedule if s['kind']=='flood_second_sender' and s['bed_id']==bed]
        return int((max(lookbacks)+self.HISTORY_MARGIN_S)*1000) if lookbacks else None
    def _capture(self,message):
        bed=message['bed_id']
        if bed not in self.latest or message['ts']>self.latest[bed]['ts']: self.latest[bed]=deepcopy(message)
        lookback=self._history_lookback_ms(bed)
        if lookback is None: return
        history=self.history.setdefault(bed,OrderedDict())
        # Never let an old replay replace the latest observed source pointer.
        if message['ts'] not in history: history[message['ts']]=deepcopy(message)
        cutoff=self.latest[bed]['ts']-lookback
        while history and next(iter(history))<cutoff: history.popitem(last=False)
        while len(history)>1200: history.popitem(last=False)
    def receive(self,topic,payload,received_ms=None,received_mono_ms=None):
        try: receipt=decode(topic,payload,received_ms)
        except (ValueError,TypeError) as exc:
            self.invalid_incoming+=1
            log.warning('Rejected attack input: %s',exc); return False
        message=receipt.data; now=receipt.received_ms
        if message['type']=='demo_control':
            if message['cmd']=='run' and self.running and self.event_log.run_id==message['run_id']: return False
            key=(message['cmd'],message['run_id'],message['ts'],message['start_at_s'])
            if key in self.controls or message['ts']<self.last_control_ts: return False
            if message['ts']==self.last_control_ts and self.last_control_ts>=0: return False
            self.controls.append(key); self.last_control_ts=message['ts']
            if message['cmd']=='reset':
                self._stop(now,'reset interrupted the attack')
                self.history.clear(); self.latest.clear(); self.own_hashes.clear()
            else:
                self._stop(now,'new run interrupted the attack')
                if self.origin_ms is not None:
                    self.history.clear(); self.latest.clear(); self.own_hashes.clear()
                self.origin_ms=message['ts']-int(message['start_at_s']*1000); self.start_ms=message['ts']
                self.event_log=EventLog(self.runs_dir,message['run_id'],self.origin_ms)
                self.states={s['id']:{'spec':s,'started':False,'done':False,'count':0,'next_ms':max(self.start_ms,self.origin_ms+int(s['start_s']*1000)), 'unavailable':None,'unavailable_ms':-10000} for s in self.schedule}
                self.running=True
            return True
        if message['type']!='vitals': return False
        digest=self._digest(topic,message)
        expiry=self.own_hashes.get(digest)
        if expiry is not None and now<=expiry: return False
        self._capture(message)
        return True
    def _event(self,now_ms,state,event,detail):
        self.event_log.write(now_ms,state['spec']['bed_id'],event,f"{state['spec']['id']}: {detail}")
    def _unavailable(self,now_ms,state,code,detail):
        if state['unavailable']!=code or now_ms-state['unavailable_ms']>=10000:
            self._event(now_ms,state,'attack_unavailable',detail)
            state['unavailable']=code; state['unavailable_ms']=now_ms
    def _source(self,spec,now_ms,script_s):
        bed=spec['bed_id']
        if spec['kind']=='replay':
            source_s=spec['source_start_s']+int(script_s-spec['start_s'])
            source_ms=((self.origin_ms+source_s*1000+500)//1000)*1000
            # Vitals are on the epoch-second grid, while controls may have any millisecond phase.
            source=self.history.get(bed,{}).get(source_ms)
            if source is not None: return source
            fixture=self.fixture_history.get((bed,source_s))
            if fixture is None: raise SourceUnavailable(f'Actual replay source T+{source_s}s was not captured; supply original fixtures for seeks')
            source=deepcopy(fixture); shift=source_ms-source['ts']; source['ts']=source_ms
            if source['nibp'] is not None: source['nibp']['ts']+=shift
            return source
        source=self.latest.get(bed)
        if source is None or now_ms-source['ts']>3000 or source['ts']>now_ms:
            fixture=self.fixture_history.get((bed,int(script_s)))
            if fixture is None: raise SourceUnavailable('No fresh actual source frame; recording may be offline')
            source=deepcopy(fixture); target_ms=((self.origin_ms+int(script_s)*1000+500)//1000)*1000; shift=target_ms-source['ts']; source['ts']=target_ms
            if source['nibp'] is not None: source['nibp']['ts']+=shift
        if spec['kind']=='flood_second_sender' and script_s>=spec['start_s']+spec['burst_s']:
            # Mask the patient with this bed's real signal from one minute ago.
            # Require a current frame for its envelope; never extend an offline
            # recording or substitute another bed / invented physiology.
            older_ms=source['ts']-self.MASK_LOOKBACK_S*1000
            older=self.history.get(bed,{}).get(older_ms)
            if older is None:
                source_s=(older_ms-self.origin_ms+500)//1000
                older=self.fixture_history.get((bed,source_s))
            if older is None: raise SourceUnavailable('Actual masking-loop source from 60 seconds earlier was not captured; supply original fixtures for seeks')
            frame=deepcopy(older)
            shift=source['ts']-frame['ts']
            frame.update(seq=source['seq'],ts=source['ts'])
            if frame['nibp'] is not None: frame['nibp']['ts']+=shift
            return frame
        return source
    def _finish(self,now_ms,state,detail):
        if state['started'] and not state['done']: self._event(now_ms,state,'attack_end',detail)
        state['done']=True
    def _stop(self,now_ms,detail):
        if self.event_log is not None:
            for state in self.states.values(): self._finish(now_ms,state,detail)
            self.event_log.close()
        self.running=False
    def tick(self,now_ms):
        now_ms=int(now_ms)
        if not self.running or now_ms<self.start_ms: return
        script_s=(now_ms-self.origin_ms)/1000
        # Expire echo hashes without an unbounded run-long fingerprint set.
        while self.own_hashes and next(iter(self.own_hashes.values()))<now_ms: self.own_hashes.popitem(last=False)
        for state in self.states.values():
            spec=state['spec']
            if state['done'] or script_s<spec['start_s']: continue
            if script_s>=spec['end_s']:
                self._finish(now_ms,state,'scheduled finite attack end'); continue
            if now_ms<state['next_ms']: continue
            rate=spec['rate_hz']
            if spec['kind']=='flood_second_sender' and script_s>=spec['start_s']+spec['burst_s']: rate=spec['steady_rate_hz']
            # Set next absolute eligibility before any source/publish failures. Never replay missed deadlines.
            state['next_ms']=now_ms+max(20,int(1000/rate))
            if state['count']>=spec.get('max_messages',10**9):
                self._finish(now_ms,state,'maximum bounded message count reached'); continue
            try:
                source=self._source(spec,now_ms,script_s)
                topic=vitals_topic(spec['bed_id'])
                try:
                    frame=transform(spec,source,script_s)
                    digest=self._digest(topic,frame)
                    sent=publish_checked(self.bus,topic,frame,qos=0,retain=False)
                except SourceUnavailable: raise
                except ValueError as exc:
                    self.invalid_outgoing+=1
                    log.warning('Rejected outgoing attack message on %s: %s',topic,exc)
                    raise
                if sent is False: raise RuntimeError('MQTT publish dropped')
            except (SourceUnavailable,ValueError,RuntimeError,OSError) as exc:
                self._unavailable(now_ms,state,type(exc).__name__,str(exc)); continue
            self.own_hashes[digest]=now_ms+5000; self.own_hashes.move_to_end(digest)
            while len(self.own_hashes)>2000: self.own_hashes.popitem(last=False)
            state['count']+=1; state['unavailable']=None
            if not state['started']:
                self._event(now_ms,state,'attack_start',spec['detail']); state['started']=True
                self._event(now_ms,state,'second_sender_on','Frames originate from the separate attack MQTT connection; payload device_id is only a claim')
                if spec['kind'] in {'network_flood','flood_second_sender'}: self._event(now_ms,state,'flood_start',f"At most {spec['rate_hz']} messages/s and {spec['max_messages']} total messages")
                if spec['kind']=='network_flood': self._event(now_ms,state,'scan_unavailable','External port scanning is not implemented; only own-broker MQTT traffic is generated')
        if script_s>=1200:
            self._stop(now_ms,'script finished at its finite 1200-second boundary')
    def close(self,now_ms): self._stop(int(now_ms),'attack process stopped')
