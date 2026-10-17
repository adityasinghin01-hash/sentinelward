"""Transforms operate on complete real source frames; never fabricate physiology."""
from copy import deepcopy
from sw_common import make_vitals
from sw_common.topics import vitals_topic
from sw_brain.io import validate

class SourceUnavailable(ValueError): pass


def transform(spec,source,script_s):
    if source is None: raise SourceUnavailable('No actual source frame for this bed')
    # Rebuild the complete source envelope while retaining extra source fields.
    frame=make_vitals(**{key:value for key,value in deepcopy(source).items() if key not in {'v','type'}})
    kind=spec['kind']
    if kind=='flatline':
        frame['ecg']=[0.]*125
        frame['monitor_alarm']={'code':'ASYSTOLE','priority':'high'}
    elif kind=='drift':
        if not isinstance(frame['abp'],list) or not any(v is not None for v in frame['abp']): raise SourceUnavailable('No observed arterial-line samples for drift')
        offset=spec['max_offset_mmhg']*min(1.,max(0.,(script_s-spec['start_s'])/spec['ramp_s']))
        frame['abp']=[None if v is None else v+offset for v in frame['abp']]
    validate(vitals_topic(frame['bed_id']),frame)
    return frame
