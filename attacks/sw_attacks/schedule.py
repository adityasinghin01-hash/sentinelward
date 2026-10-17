"""Load doc-12 timings and enforce finite, bounded demonstration scenarios."""
from copy import deepcopy
from importlib.resources import files
import math
from pathlib import Path
import yaml

KINDS={'replay','flatline','flood_second_sender','drift','network_flood','second_sender'}


def load_schedule(path=None):
    source=Path(path) if path else Path(__file__).resolve().parents[1]/'schedule.yaml'
    if not source.exists() and path is None: source=files('sw_attacks').joinpath('schedule.yaml')
    data=yaml.safe_load(source.read_text())
    if not isinstance(data,dict) or data.get('script_duration_s')!=1200 or not isinstance(data.get('attacks'),list): raise ValueError('Expected finite 1200-second ward schedule')
    ids=set()
    for spec in data['attacks']:
        required={'id','bed_id','kind','start_s','end_s','start_basis','end_basis','rate_hz','detail'}
        if not isinstance(spec,dict) or not required.issubset(spec): raise ValueError('Incomplete attack specification')
        if spec['id'] in ids or spec['kind'] not in KINDS or spec['bed_id'] not in {'B05','B06','B07','B10','B11','B12'}: raise ValueError('Invalid scenario identity')
        ids.add(spec['id'])
        for key in ('start_s','end_s','rate_hz'):
            value=spec[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError('Invalid scenario time/rate')
        if not 0<=spec['start_s']<spec['end_s']<=1200 or not 0<spec['rate_hz']<=50: raise ValueError('Attack exceeds finite duration/rate')
        if spec['kind'] in {'network_flood','flood_second_sender'}:
            count=spec.get('max_messages',0)
            if type(count) is not int or not 0<count<=500: raise ValueError('Flood exceeds 500-message bound')
        if spec['kind']=='flood_second_sender':
            for key in ('burst_s','steady_rate_hz'):
                value=spec.get(key)
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError('Invalid burst or steady rate')
            if not 0<spec['steady_rate_hz']<=50 or not 0<=spec['burst_s']<=spec['end_s']-spec['start_s']: raise ValueError('Invalid burst or steady rate')
        if spec['kind']=='replay' and not 0<=spec.get('source_start_s',-1)<spec['start_s']: raise ValueError('Replay needs earlier source history')
        if spec['kind']=='drift' and (spec.get('ramp_s',0)<=0 or not 0<=spec.get('max_offset_mmhg',-1)<=15): raise ValueError('Invalid pressure ramp')
    return deepcopy(data['attacks'])
