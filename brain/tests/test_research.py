import hashlib
import json

import numpy as np
import pytest

from sw_brain.research import Research, upsample


def test_resampling_preserves_missing_masks_and_never_duplicates_leads():
    window = {'ecg': [1.] * 1250, 'ppg': [2.] * 1250}
    window['ecg'][600] = None
    signal, mask = upsample(window)
    assert signal.shape == mask.shape == (2, 2500)
    assert mask.dtype == np.bool_
    assert not mask[0, 1200]
    assert not mask[:, 0].any()
    assert np.isfinite(signal).all()
    assert signal[0, 1200] == 0


def test_primary_seed_and_its_threshold_not_seed_mean():
    class Models:
        def predict_m2(self, signal, mask):
            assert signal.shape == (2, 2500)
            return {'seeds': {'20261015': {'probability': .62, 'threshold': .61},
                              '20261016': {'probability': .01, 'threshold': .5}}}
    research = Research(models=Models())
    result = research.m2({'ecg': [1.] * 1250, 'ppg': [2.] * 1250})
    assert result['score'] == .62
    assert result['positive'] is True
    assert result['threshold'] == .61
    assert result['extra']['resampled_from_125hz'] is True


def test_m2_load_failure_is_explicit_fallback():
    class Broken:
        def predict_m2(self, *args):
            raise ImportError('torch missing')
    result = Research(models=Broken()).m2({'ecg': [1.] * 1250, 'ppg': [2.] * 1250})
    assert result['status'] == 'unavailable'
    assert 'torch missing' in result['extra']['unavailable_reason']


def test_m4_channel_order_must_be_verified_before_calling_artifact():
    assert Research().m4({}, {})['status'] == 'unavailable'


def test_m5_hash_checked_before_deserialization(tmp_path):
    path = tmp_path / 'model.joblib'
    path.write_bytes(b'tampered')
    result = Research(m5_path=path).m5({}, 'MON-01')
    assert result['status'] == 'unavailable'
    assert 'SHA-256' in result['extra']['unavailable_reason']


def test_nonfinite_or_out_of_range_artifact_result_falls_back():
    class Models:
        def predict_m2(self, *args):
            return {'seeds': {'20261015': {'probability': float('nan'), 'threshold': .5}}}
    assert Research(models=Models()).m2({'ecg': [1.] * 1250, 'ppg': [2.] * 1250})['status'] == 'unavailable'


def test_slow_artifact_has_bounded_deadline_then_matching_result_is_available():
    import threading
    import time
    entered=threading.Event(); release=threading.Event()
    class Slow:
        def predict_m2(self,*args):
            entered.set(); release.wait(2)
            return {'seeds':{'20261015':{'probability':.9,'threshold':.7}}}
    research=Research(models=Slow(),timeout_s=.01)
    window={'ecg':[1.]*1250,'ppg':[2.]*1250,'window_start':10000}
    started=time.monotonic()
    try:
        result=research.m2(window)
        assert result['status']=='unavailable'
        assert time.monotonic()-started<.2
        assert 'deadline' in result['extra']['unavailable_reason']
        assert entered.wait(1)
    finally:
        release.set()
    assert research.m2(window)['score']==.9


def test_research_cache_never_crosses_beds_on_same_window():
    class Models:
        def predict_m2(self,signal,mask):
            return {'seeds':{'20261015':{'probability':float(signal[0,100]),'threshold':.5}}}
    research=Research(models=Models())
    first=research.m2({'bed_id':'B01','window_start':0,'ecg':[.1]*1250,'ppg':[.2]*1250})
    second=research.m2({'bed_id':'B02','window_start':0,'ecg':[.9]*1250,'ppg':[.2]*1250})
    assert first['score']<.2
    assert second['score']>.8
