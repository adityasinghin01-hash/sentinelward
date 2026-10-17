"""Five-second receive-side MQTT features, with bounded online statistics.

Payload identities never establish sender identity. Broker PUBLISH logs supply
client IDs; connection/auth observations are separate from received messages.
"""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import threading
import time

from sw_common import topic_for, validate
from .policy import DEVICES


@dataclass
class Moments:
    count: int = 0
    mean: float = 0
    m2: float = 0

    def add(self, value):
        self.count += 1
        delta=value-self.mean
        self.mean += delta/self.count
        self.m2 += delta*(value-self.mean)

    def values(self):
        return (self.mean, math.sqrt(max(0,self.m2/self.count))) if self.count else (None,None)


@dataclass
class Window:
    count: int = 0
    size: int = 0
    malformed: int = 0
    gaps: int = 0
    repeats: int = 0
    seq_seen: bool = False
    payload: Moments = field(default_factory=Moments)
    iat: Moments = field(default_factory=Moments)
    senders: set = field(default_factory=set)
    sender_overflow: bool = False
    connects: int = 0
    latest_ts: int | None = None


class Extractor:
    def __init__(self):
        self._windows={d:{} for d in DEVICES}
        self._last_arrival={}
        self._last_seq={}
        self._last_ts={}
        self.logs_available=False
        self.log_coverage_start=None
        self.unattributed_auth_failures=0
        self._control_ts=-1
        self._lock=threading.RLock()

    def _window(self, device, timestamp):
        start=timestamp//5000*5000
        windows=self._windows[device]
        if start not in windows:
            windows[start]=Window()
            # Out-of-order log backlog cannot allocate unlimited windows.
            for old in sorted(windows)[:-3]: del windows[old]
        return windows.get(start)

    def observe(self, topic, payload, received_ms):
        match=re.fullmatch(r'ward/bed/B(0[1-9]|1[0-2])/vitals',topic)
        if not match: return
        device='MON-'+match[1]
        with self._lock:
            window=self._window(device,received_ms)
            if window is None: return
            window.count += 1
            window.size += len(payload)
            window.payload.add(len(payload))
            previous=self._last_arrival.get(device)
            if previous is not None and received_ms>=previous: window.iat.add(received_ms-previous)
            self._last_arrival[device]=received_ms
            try:
                if len(payload)>1_048_576: raise ValueError('Oversized message')
                message=json.loads(payload)
                if not isinstance(message,dict) or validate(message) or topic_for(message)!=topic or message['device_id']!=device:
                    raise ValueError('Invalid contract message')
            except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
                window.malformed += 1
                return
            seq=message['seq']
            previous=self._last_seq.get(device)
            window.seq_seen=True
            if previous is not None:
                if seq<=previous: window.repeats += 1
                else: window.gaps += max(0,seq-previous-1)
            self._last_seq[device]=max(seq,previous) if previous is not None else seq
            self._last_ts[device]=(message['ts'],received_ms)
            window.latest_ts=message['ts']

    def control(self, message):
        if not isinstance(message,dict) or message.get('type')!='demo_control' or validate(message):
            return
        with self._lock:
            if message['ts']<=self._control_ts: return
            self._control_ts=message['ts']
            self._last_seq.clear(); self._last_ts.clear(); self._last_arrival.clear()
            self._windows={d:{} for d in DEVICES}

    def log(self, line):
        match=re.match(r'^(\d+): (.*)',line)
        if not match: return
        timestamp=int(match[1])*1000
        text=match[2]
        with self._lock:
            connected=re.search(r"New client connected .* as (\S+) .*u'(MON-\d{2})'",text)
            if connected and connected[2] in DEVICES:
                window=self._window(connected[2],timestamp)
                if window: window.connects+=1
            published=re.search(r"Received PUBLISH from (\S+) .*'ward/bed/B(0[1-9]|1[0-2])/vitals'",text)
            if published:
                window=self._window('MON-'+published[2],timestamp)
                # Bound sender set; normal installation has <20 identities.
                if window:
                    if len(window.senders)<1024: window.senders.add(published[1])
                    elif published[1] not in window.senders: window.sender_overflow=True
            if 'not authorised' in text.lower() or 'not authorized' in text.lower():
                self.unattributed_auth_failures += 1

    def snapshot(self, device, window_start):
        if device not in DEVICES or window_start%5000: raise ValueError('Invalid device/window')
        with self._lock:
            window=self._windows[device].get(window_start,Window())
            payload_mean,payload_std=window.payload.values()
            iat_mean,iat_std=window.iat.values()
            logs_known=self.logs_available and (self.log_coverage_start is None or window_start>=self.log_coverage_start)
            latest=self._last_ts.get(device)
            if latest is not None and latest[1]>=window_start+5000:
                candidates=[w.latest_ts for start,w in sorted(self._windows[device].items())
                            if start<=window_start and w.latest_ts is not None]
                latest=(candidates[-1],0) if candidates else None
            age=window_start+5000-latest[0] if latest else None
            result={'v':1,'type':'net_features','device_id':device,'window_start':window_start,'window_s':5,
                    'msgs_per_s':window.count/5,'bytes_per_s':window.size/5,
                    'iat_mean_ms':iat_mean,'iat_std_ms':iat_std,
                    'payload_mean':payload_mean,'payload_std':payload_std,
                    'senders':len(window.senders) if logs_known and not window.sender_overflow else None,
                    'connects_per_s':window.connects/5 if logs_known else None,
                    'malformed':window.malformed,'seq_gaps':window.gaps if window.seq_seen else None,
                    'seq_repeats':window.repeats if window.seq_seen else None,
                    'stale_ms':age if age is not None and age>=0 else None}
            return result


class LogTail:
    """Rotation/truncation aware, bounded reads; absent/unreadable logs mean unknown."""
    def __init__(self, path, extractor, *, clock=None):
        self.path,self.extractor=Path(path),extractor
        self.identity=None
        self.offset=0
        self.clock=clock or (lambda:time.time_ns()//1_000_000)

    def poll(self):
        try:
            with self.path.open('rb') as handle:
                info=handle.fileno()
                import os
                st=os.fstat(info)
                identity=(st.st_dev,st.st_ino)
                if identity!=self.identity or st.st_size<self.offset:
                    # Start live, without replaying a potentially huge broker
                    # history. On rotation/truncation read the new file from
                    # its beginning; its first publications are live evidence.
                    self.offset=st.st_size if self.identity is None else 0
                    self.identity=identity
                    self.extractor.log_coverage_start=(self.clock()//5000+1)*5000
                handle.seek(self.offset)
                for _ in range(10000):
                    offset=handle.tell()
                    # Read only the size sampled for this poll. Otherwise live
                    # appends can take tell() beyond st_size and falsely mark
                    # a fully caught-up log unavailable at publication time.
                    remaining=st.st_size-offset
                    if remaining<=0: break
                    line=handle.readline(min(16384,remaining))
                    if not line: break
                    if not line.endswith(b'\n'):
                        handle.seek(offset)
                        break
                    self.extractor.log(line.decode('utf-8',errors='replace'))
                self.offset=handle.tell()
                self.extractor.logs_available=self.offset==st.st_size
        except (OSError,UnicodeError):
            self.extractor.logs_available=False
