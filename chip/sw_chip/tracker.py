"""Rebuild the brain's M2 pre-alarm window from the vitals stream, per bed.

Mirrors brain/sw_brain/service.py BrainService.receive (round2 @d6176fb): a monitor alarm
that starts a new alarm episode takes the 10 one-second chunks at ts-10 s .. ts-1 s (they
must be contiguous) as the pre-alarm window; that is the window the brain's M2 trees score.
Episode rule (same as the brain): an alarm frame continues the episode if the alarm hold
(max(ts+40 s, now+30 s)) has not expired, the code is the same, and the frame is the same
second or the next contiguous second of an alarmed frame.

Differences, by design (this client only has subscribe rights on ward/bed/+/vitals):
bedside patient_ok and ward/demo/control resets are not seen. A demo reset restarts seq at 1,
which this tracker sees as an out-of-order/gap and clears the bed's chunks, as the brain's
own window assembler does.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isfinite

FS = 125
ALARM_CODES = ('VTACH', 'VFIB', 'BRADY', 'TACHY', 'ASYSTOLE')
HOLD_TS_MS = 40000
HOLD_NOW_MS = 30000


def check_vitals(topic, message):
    """Return None if message is a usable v1 vitals chunk on its own bed topic, else a reason."""
    if not isinstance(message, dict) or message.get('v') != 1 or message.get('type') != 'vitals':
        return 'not v1 vitals'
    bed = message.get('bed_id')
    if not isinstance(bed, str) or topic != f'ward/bed/{bed}/vitals':
        return 'bed_id does not match topic'
    for name in ('seq', 'ts'):
        if type(message.get(name)) is not int or message[name] < 0:
            return name + ' must be a nonnegative integer'
    if message['ts'] % 1000 or message.get('fs') != FS:
        return 'expected aligned one-second chunks at 125 Hz'
    for name in ('ecg', 'ppg', 'abp'):
        x = message.get(name)
        if x is None:
            continue
        if not isinstance(x, list) or len(x) != FS:
            return name + ' must be null or 125 samples'
        for s in x:
            if s is not None and not (type(s) in (int, float) and isfinite(s)):
                return name + ' samples must be finite numbers or null'
    alarm = message.get('monitor_alarm')
    if alarm is not None and (not isinstance(alarm, dict) or alarm.get('code') not in ALARM_CODES):
        return 'invalid monitor alarm'
    return None


@dataclass
class _Bed:
    chunks: deque = field(default_factory=lambda: deque(maxlen=10))
    last_message: dict | None = None
    last_seq: int | None = None
    last_ts: int | None = None
    alarm_until_ms: int = 0
    last_alarm_code: str | None = None
    alarm_ts: int | None = None


def _window(bed_id, chunks):
    """Same layout as BrainService._window_from_chunks (ecg/ppg always, abp only if present)."""
    w = {'bed_id': bed_id, 'window_start': chunks[0]['ts']}
    for ch in ('ecg', 'ppg'):
        w[ch] = [v for c in chunks for v in (c.get(ch) or [None] * FS)]
    w['abp'] = ([v for c in chunks for v in (c.get('abp') or [None] * FS)]
                if any(c.get('abp') for c in chunks) else None)
    return w


class AlarmTracker:
    def __init__(self):
        self.beds = {}

    def reset(self):
        self.beds.clear()

    def ingest(self, message, now_ms):
        """Feed one validated vitals message; return (code, alarm_ts, window) for a new alarm
        episode that has a full pre-alarm window (exactly when the brain scores M2), else None."""
        bed_id = message['bed_id']
        st = self.beds.setdefault(bed_id, _Bed())
        if st.last_seq is not None and message['seq'] < st.last_seq and message['ts'] > st.last_ts:
            # seq restarted with time moving on: a demo reset/run (the brain resets all beds then).
            self.beds[bed_id] = st = _Bed()
        out = None
        alarm = message.get('monitor_alarm')
        if alarm:
            prev = (st.last_message or {}).get('monitor_alarm') or {}
            same = (st.alarm_until_ms >= now_ms and st.last_alarm_code == alarm['code'] and
                    (message['ts'] == st.alarm_ts or
                     (prev.get('code') == alarm['code'] and st.last_ts is not None and
                      message['ts'] == st.last_ts + 1000 and message['seq'] == st.last_seq + 1)))
            st.alarm_until_ms = max(st.alarm_until_ms, message['ts'] + HOLD_TS_MS, now_ms + HOLD_NOW_MS)
            if not same:
                st.alarm_ts = message['ts']
                c = st.chunks
                if len(c) == 10 and c[0]['ts'] == message['ts'] - 10000 and c[-1]['ts'] == message['ts'] - 1000:
                    out = (alarm['code'], message['ts'], _window(bed_id, list(c)))
            st.last_alarm_code = alarm['code']
        if st.last_seq is not None and (message['seq'] <= st.last_seq or message['ts'] <= st.last_ts):
            return out          # the brain drops duplicate / out-of-order frames from its windows
        if st.last_seq is not None and (message['seq'] != st.last_seq + 1 or message['ts'] != st.last_ts + 1000):
            st.chunks.clear()
        st.last_seq, st.last_ts, st.last_message = message['seq'], message['ts'], message
        st.chunks.append(message)
        return out
