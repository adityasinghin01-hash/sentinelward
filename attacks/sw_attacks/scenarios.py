"""Transforms operate on complete real source frames; never fabricate physiology."""
from copy import deepcopy
from sw_brain.io import validate

class SourceUnavailable(ValueError): pass


def transform(spec,source,script_s):
    if source is None: raise SourceUnavailable('No actual source frame for this bed')
    frame=deepcopy(source)
    kind=spec['kind']
    if kind=='flatline':
        frame['ecg']=[0.]*125
        frame['monitor_alarm']={'code':'ASYSTOLE','priority':'high'}
    elif kind=='drift':
        if not isinstance(frame['abp'],list) or not any(v is not None for v in frame['abp']): raise SourceUnavailable('No observed arterial-line samples for drift')
        offset=spec['max_offset_mmhg']*min(1.,max(0.,(script_s-spec['start_s'])/spec['ramp_s']))
        frame['abp']=[None if v is None else v+offset for v in frame['abp']]
    validate(f"ward/bed/{frame['bed_id']}/vitals",frame)
    return frame
