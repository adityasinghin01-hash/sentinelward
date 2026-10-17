"""Brain-owned 125 Hz windows, written 2026-10-17."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite
import re


def _validate_chunk(message):
    if not isinstance(message, dict) or type(message.get('v')) is not int or message['v'] != 1 or message.get('type') != 'vitals':
        raise ValueError('Expected v1 vitals')
    for name, pattern in [('bed_id', r'B(0[1-9]|1[0-2])'),
                          ('device_id', r'MON-(0[1-9]|1[0-2])')]:
        if not isinstance(message.get(name), str) or re.fullmatch(pattern, message[name]) is None:
            raise ValueError('Invalid ' + name)
    for name in ('seq', 'ts'):
        if type(message.get(name)) is not int or message[name] < 0:
            raise ValueError(name + ' must be a nonnegative integer')
    if message['ts'] % 1000 or type(message.get('fs')) is not int or message['fs'] != 125:
        raise ValueError('Expected aligned one-second chunks at 125 Hz')
    for name in ('ecg', 'ppg', 'abp'):
        samples = message.get(name)
        if samples is None:
            continue
        if not isinstance(samples, list) or len(samples) != 125:
            raise ValueError(name + ' must be null or 125 samples')
        for sample in samples:
            if sample is not None:
                try:
                    valid = type(sample) in (int, float) and isfinite(sample)
                except OverflowError:
                    valid = False
                if not valid:
                    raise ValueError(name + ' samples must be finite numbers or null')
    alarm = message.get('monitor_alarm')
    if alarm is not None and (not isinstance(alarm, dict) or set(alarm) != {'code', 'priority'} or
                              alarm['code'] not in ('VTACH', 'VFIB', 'BRADY', 'TACHY', 'ASYSTOLE') or
                              alarm['priority'] not in ('high', 'medium', 'low')):
        raise ValueError('Invalid monitor alarm')


def assemble_window(chunks):
    """Snapshot ten accepted seconds, retaining missing samples and alarms."""
    first, last = chunks[0], chunks[-1]
    window = dict(bed_id=first['bed_id'], device_id=first['device_id'],
                  window_start=first['ts'], window_s=10, sample_rate_hz=125,
                  seq_first=first['seq'], seq_last=last['seq'],
                  monitor_alarms=[deepcopy(c['monitor_alarm']) for c in chunks
                                  if c.get('monitor_alarm') is not None])
    for channel in ('ecg', 'ppg', 'abp'):
        samples = [sample for chunk in chunks for sample in
                   (chunk[channel] if chunk.get(channel) is not None else [None] * 125)]
        window[channel] = samples
        window[channel + '_valid'] = [sample is not None for sample in samples]
    return window


@dataclass
class _Stream:
    device: str
    seconds: deque = field(default_factory=lambda: deque(maxlen=10))


class VitalsWindowAssembler:
    """Emit complete epoch-aligned 10 s windows at 5 s intervals per bed.

    Rejected frames leave accepted history untouched. A new device or a forward
    sequence/time gap starts a new ten-second warmup; reset forgets all streams.
    """

    def __init__(self):
        self._streams = {}

    def reset(self):
        self._streams.clear()

    def ingest(self, message):
        _validate_chunk(message)
        bed, device = message['bed_id'], message['device_id']
        stream = self._streams.get(bed)
        if stream is None or stream.device != device:
            stream = _Stream(device)
            self._streams[bed] = stream
        if stream.seconds:
            previous = stream.seconds[-1]
            if message['seq'] <= previous['seq'] or message['ts'] <= previous['ts']:
                raise ValueError('Duplicate or out-of-order vitals')
            if message['seq'] != previous['seq'] + 1 or message['ts'] != previous['ts'] + 1000:
                stream.seconds.clear()
        stream.seconds.append(deepcopy(message))
        if len(stream.seconds) == 10 and (message['ts'] + 1000) % 5000 == 0:
            return assemble_window(list(stream.seconds))
        return None
